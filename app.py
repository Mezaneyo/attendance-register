"""
Attendance Register - a simple attendance system (classes/groups, members, sessions, reports, export)
Developer: Chisomo Pen Chitembeya
Setup: pip install flask      Run: python app.py      Open: http://127.0.0.1:5000
Exports (Excel, PDF, Word, CSV) use only the Python standard library - nothing else to install.
"""
import csv, io, logging, os, sqlite3, sys, zipfile
from datetime import date, datetime
from xml.sax.saxutils import escape as esc
from flask import Flask, Response, abort, flash, g, redirect, render_template, request, url_for
from werkzeug.exceptions import HTTPException

NAME = "Attendance Register"
VERSION = "1.0"
DEVELOPER = "Chisomo Pen Chitembeya"
MAX_NAMES = 200  # most names accepted in one "add members" box
STATUSES = ["Present", "Late", "Absent", "Excused"]
COLORS = {"Present": "success", "Late": "warning", "Absent": "danger", "Excused": "secondary"}
DEFAULTS = {"org": "My Organisation", "min_pct": "75"}
HERE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))  # _MEIPASS = inside the .exe


def data_dir():
    """Where the database and log live: next to the code, in the app folder on Android, in %APPDATA% for the .exe."""
    d = (os.environ.get("ATT_DATA") or os.environ.get("ANDROID_PRIVATE")
         or (os.path.join(os.environ.get("APPDATA", ""), "AttendanceRegister") if getattr(sys, "frozen", False)
             else os.path.dirname(os.path.abspath(__file__))))
    os.makedirs(d, exist_ok=True)
    return d


DB = os.path.join(data_dir(), "attendance.db")
logging.basicConfig(filename=os.path.join(data_dir(), "attendance.log"), level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
app = Flask(__name__, template_folder=os.path.join(HERE, "templates"), static_folder=os.path.join(HERE, "static"))
app.secret_key = os.environ.get("SECRET_KEY", "change-me")


@app.errorhandler(Exception)
def crash(e):
    """Any unexpected error is written to attendance.log (with the full traceback) instead of killing the app."""
    if isinstance(e, HTTPException):
        return e
    logging.exception("Unhandled error on %s %s", request.method, request.path)
    return render_template("error.html"), 500


# ---------- database ----------
def q(sql, args=(), one=False):
    if "db" not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
    rows = g.db.execute(sql, args).fetchall()
    g.db.commit()
    return (rows[0] if rows else None) if one else rows


@app.teardown_appcontext
def close_db(_):
    c = g.pop("db", None)
    if c:
        c.close()


def init_db():
    """classes -> members and sessions; marks = the status of one member in one session."""
    con = sqlite3.connect(DB)
    con.executescript("""
    CREATE TABLE IF NOT EXISTS classes(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT);
    CREATE TABLE IF NOT EXISTS members(id INTEGER PRIMARY KEY AUTOINCREMENT, class_id INTEGER, name TEXT, code TEXT);
    CREATE TABLE IF NOT EXISTS sessions(id INTEGER PRIMARY KEY AUTOINCREMENT, class_id INTEGER, day TEXT, title TEXT);
    CREATE TABLE IF NOT EXISTS marks(session_id INTEGER, member_id INTEGER, status TEXT, PRIMARY KEY(session_id, member_id));
    CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);""")
    con.commit()
    con.close()


def cfg():
    """Settings saved on the Settings page, with defaults."""
    if "cfg" not in g:
        g.cfg = dict(DEFAULTS, **{r["key"]: r["value"] for r in q("SELECT * FROM settings")})
    return g.cfg


def min_pct():
    try:
        return float(cfg()["min_pct"])
    except ValueError:
        return 75.0


@app.context_processor
def inject():
    return dict(cfg=cfg(), name=NAME, version=VERSION, developer=DEVELOPER, statuses=STATUSES, colors=COLORS)


@app.template_filter("pct")
def pct(n):
    return f"{n:.1f}%"


def clean(text, n=80):
    """Tidy a typed name: remove extra spaces and cut it to n letters."""
    return " ".join(str(text).split())[:n]


def new_id():
    return q("SELECT last_insert_rowid() AS id", one=True)["id"]


# ---------- the attendance maths ----------
def class_data(cid):
    """For one class: members with their counts and %, the sessions, and overall numbers.
    attendance % = (Present + Late) / (Present + Late + Absent) x 100   (Excused sessions are not counted)"""
    cls = q("SELECT * FROM classes WHERE id=?", (cid,), one=True)
    if not cls:
        abort(404)
    members = q("SELECT * FROM members WHERE class_id=? ORDER BY LOWER(name)", (cid,))
    counts = {}
    for k in q("""SELECT k.member_id, k.status, COUNT(*) AS n FROM marks k JOIN sessions s ON s.id = k.session_id
                  WHERE s.class_id=? GROUP BY k.member_id, k.status""", (cid,)):
        counts.setdefault(k["member_id"], {})[k["status"]] = k["n"]
    rows = []
    for m in members:
        p, l, a, e = (counts.get(m["id"], {}).get(s, 0) for s in STATUSES)
        counted = p + l + a
        pc = (p + l) / counted * 100 if counted else 0.0
        rows.append(dict(m, present=p, late=l, absent=a, excused=e, counted=counted, pct=pc,
                         none=counted == 0, low=counted > 0 and pc < min_pct()))
    sessions = q("""SELECT s.*, COALESCE(SUM(k.status='Present'),0) AS p, COALESCE(SUM(k.status='Late'),0) AS l,
                    COALESCE(SUM(k.status='Absent'),0) AS a, COALESCE(SUM(k.status='Excused'),0) AS e
                    FROM sessions s LEFT JOIN marks k ON k.session_id = s.id WHERE s.class_id=?
                    GROUP BY s.id ORDER BY s.day DESC, s.id DESC""", (cid,))
    rated = [r for r in rows if r["counted"]]
    stats = dict(members=len(rows), sessions=len(sessions), min_pct=min_pct(), low=sum(r["low"] for r in rows),
                 average=sum(r["pct"] for r in rated) / len(rated) if rated else 0.0)
    return cls, rows, sessions, stats


# ---------- classes ----------
@app.route("/")
def index():
    classes = q("""SELECT c.*, (SELECT COUNT(*) FROM members m WHERE m.class_id=c.id) AS members,
                   (SELECT COUNT(*) FROM sessions s WHERE s.class_id=c.id) AS sessions
                   FROM classes c ORDER BY LOWER(c.name)""")
    return render_template("index.html", classes=classes)


@app.post("/class/add")
def add_class():
    name = clean(request.form.get("name", ""), 60)
    if not name:
        flash("Enter a name for the class or group.", "danger")
        return redirect(url_for("index"))
    q("INSERT INTO classes(name) VALUES(?)", (name,))
    flash("Class created. Now add the members.", "success")
    return redirect(url_for("class_page", cid=new_id()))


@app.route("/class/<int:cid>")
def class_page(cid):
    cls, rows, sessions, stats = class_data(cid)
    return render_template("class.html", cls=cls, rows=rows, sessions=sessions, s=stats, today=date.today().isoformat())


@app.post("/class/<int:cid>/delete")
def delete_class(cid):
    q("DELETE FROM marks WHERE session_id IN (SELECT id FROM sessions WHERE class_id=?)", (cid,))
    for t in ("sessions", "members"):
        q(f"DELETE FROM {t} WHERE class_id=?", (cid,))
    q("DELETE FROM classes WHERE id=?", (cid,))
    flash("Class deleted.", "success")
    return redirect(url_for("index"))


# ---------- members ----------
@app.post("/class/<int:cid>/members/add")
def add_members(cid):
    if not q("SELECT 1 FROM classes WHERE id=?", (cid,), one=True):
        abort(404)
    added = 0
    for line in request.form.get("names", "").splitlines()[:MAX_NAMES]:
        name, _, code = line.partition(",")
        name, code = clean(name), clean(code, 30)
        if name:
            q("INSERT INTO members(class_id,name,code) VALUES(?,?,?)", (cid, name, code))
            added += 1
    flash(f"{added} member(s) added." if added else "Type at least one name (one name per line).",
          "success" if added else "danger")
    return redirect(url_for("class_page", cid=cid) + "#members")


@app.route("/member/<int:mid>/edit", methods=["GET", "POST"])
def edit_member(mid):
    m = q("SELECT * FROM members WHERE id=?", (mid,), one=True)
    if not m:
        abort(404)
    if request.method == "POST":
        name, code = clean(request.form.get("name", "")), clean(request.form.get("code", ""), 30)
        if name:
            q("UPDATE members SET name=?, code=? WHERE id=?", (name, code, mid))
            flash("Member updated.", "success")
            return redirect(url_for("class_page", cid=m["class_id"]) + "#members")
        flash("The name cannot be empty.", "danger")
    history = q("""SELECT s.day, s.title, k.status FROM marks k JOIN sessions s ON s.id = k.session_id
                   WHERE k.member_id=? ORDER BY s.day DESC, s.id DESC""", (mid,))
    return render_template("edit_member.html", m=m, history=history)


@app.post("/member/<int:mid>/delete")
def delete_member(mid):
    m = q("SELECT * FROM members WHERE id=?", (mid,), one=True)
    if not m:
        abort(404)
    q("DELETE FROM marks WHERE member_id=?", (mid,))
    q("DELETE FROM members WHERE id=?", (mid,))
    flash("Member deleted.", "success")
    return redirect(url_for("class_page", cid=m["class_id"]) + "#members")


# ---------- sessions (taking attendance) ----------
@app.post("/class/<int:cid>/session/add")
def add_session(cid):
    if not q("SELECT 1 FROM classes WHERE id=?", (cid,), one=True):
        abort(404)
    day = request.form.get("day") or date.today().isoformat()
    try:
        datetime.strptime(day, "%Y-%m-%d")
    except ValueError:
        flash("Choose a valid date.", "danger")
        return redirect(url_for("class_page", cid=cid) + "#sessions")
    q("INSERT INTO sessions(class_id,day,title) VALUES(?,?,?)", (cid, day, clean(request.form.get("title", ""), 60)))
    return redirect(url_for("take", sid=new_id()))


@app.route("/session/<int:sid>", methods=["GET", "POST"])
def take(sid):
    s = q("SELECT s.*, c.name AS cname FROM sessions s JOIN classes c ON c.id = s.class_id WHERE s.id=?", (sid,), one=True)
    if not s:
        abort(404)
    members = q("SELECT * FROM members WHERE class_id=? ORDER BY LOWER(name)", (s["class_id"],))
    if request.method == "POST":
        for m in members:
            st = request.form.get(f"status_{m['id']}")
            if st in STATUSES:  # a member missing from the form is left unmarked
                q("INSERT OR REPLACE INTO marks(session_id,member_id,status) VALUES(?,?,?)", (sid, m["id"], st))
        flash("Attendance saved.", "success")
        return redirect(url_for("class_page", cid=s["class_id"]) + "#sessions")
    current = {k["member_id"]: k["status"] for k in q("SELECT * FROM marks WHERE session_id=?", (sid,))}
    return render_template("take.html", s=s, members=members, current=current)


@app.post("/session/<int:sid>/delete")
def delete_session(sid):
    s = q("SELECT * FROM sessions WHERE id=?", (sid,), one=True)
    if not s:
        abort(404)
    q("DELETE FROM marks WHERE session_id=?", (sid,))
    q("DELETE FROM sessions WHERE id=?", (sid,))
    flash("Session deleted.", "success")
    return redirect(url_for("class_page", cid=s["class_id"]) + "#sessions")


# ---------- settings ----------
@app.route("/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        org = clean(request.form.get("org", ""), 60) or DEFAULTS["org"]
        try:
            pc = float(request.form.get("min_pct", ""))
            assert 0 <= pc <= 100
        except (ValueError, AssertionError):
            flash("The minimum attendance must be a number from 0 to 100.", "danger")
            return redirect(url_for("settings"))
        for k, v in (("org", org), ("min_pct", f"{pc:g}")):
            q("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (k, v))
        flash("Settings saved.", "success")
        return redirect(url_for("settings"))
    return render_template("settings.html")


@app.post("/reset")
def reset():
    for t in ("marks", "sessions", "members", "classes"):
        q(f"DELETE FROM {t}")
    flash("All data cleared.", "warning")
    return redirect(url_for("index"))


# ---------- export: Excel, PDF, Word, CSV (standard library only) ----------
HEAD = ["Name", "ID", "Sessions", "Present", "Late", "Absent", "Excused", "Attendance %", "Status"]


def fmt_val(v):
    return v if isinstance(v, str) else f"{v:,.1f}".rstrip("0").rstrip(".")


def cs(v):  # spreadsheet cell style: 0 = normal, 2 = number with 2 decimals
    return 0 if isinstance(v, str) or float(v).is_integer() else 2


def report(cid):
    cls, rows, sessions, st = class_data(cid)
    data = [[r["name"], r["code"] or "", r["counted"], r["present"], r["late"], r["absent"], r["excused"],
             round(r["pct"], 1), "No data" if r["none"] else "Low" if r["low"] else "OK"] for r in rows]
    totals = [("Members", st["members"]), ("Sessions held", st["sessions"]),
              ("Average attendance %", round(st["average"], 1)), ("Members below the minimum (%g%%)" % st["min_pct"], st["low"])]
    sub = (cfg()["org"] + " | Generated " + date.today().strftime("%d %B %Y")
           + " | Present and Late count as attended, Excused is not counted")
    return cls["name"] + " - Attendance Report", sub, data, totals


def cell_text(j, v):
    return fmt_val(v)


def zip_bytes(parts):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in parts.items():
            z.writestr(name, data)
    return buf.getvalue()


def make_xlsx(title, sub, rows, totals):
    grid = [[(title, 1)], [(sub, 0)], [], [(h, 1) for h in HEAD]]
    grid += [[(v, cs(v)) for v in r] for r in rows] + [[]]
    grid += [[(l, 1), (v, cs(v))] for l, v in totals]
    xml = []
    for n, row in enumerate(grid, 1):
        cells = ""
        for j, (v, st) in enumerate(row):
            ref = f"{chr(65 + j)}{n}"
            cells += (f'<c r="{ref}" s="{st}"><v>{v}</v></c>' if isinstance(v, (int, float))
                      else f'<c r="{ref}" s="{st}" t="inlineStr"><is><t>{esc(str(v))}</t></is></c>')
        xml.append(f'<row r="{n}">{cells}</row>')
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    head = '<?xml version="1.0" encoding="UTF-8"?>'
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    return zip_bytes({
        "[Content_Types].xml": head + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>',
        "_rels/.rels": head + f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="{rel}/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        "xl/workbook.xml": head + f'<workbook xmlns="{ns}" xmlns:r="{rel}"><sheets><sheet name="Attendance" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": head + f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="{rel}/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="{rel}/styles" Target="styles.xml"/></Relationships>',
        "xl/styles.xml": head + f'<styleSheet xmlns="{ns}"><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts><fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills><borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/><xf numFmtId="4" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>',
        "xl/worksheets/sheet1.xml": head + f'<worksheet xmlns="{ns}"><cols><col min="1" max="1" width="40" customWidth="1"/><col min="2" max="10" width="14" customWidth="1"/></cols><sheetData>{"".join(xml)}</sheetData></worksheet>'})


def make_docx(title, sub, rows, totals):
    def p(text, bold=False, size=22):
        return (f'<w:p><w:r><w:rPr>{"<w:b/>" if bold else ""}<w:sz w:val="{size}"/></w:rPr>'
                f'<w:t xml:space="preserve">{esc(text)}</w:t></w:r></w:p>')
    tr = lambda cells, bold=False: "<w:tr>" + "".join(
        f'<w:tc><w:tcPr><w:tcW w:w="0" w:type="auto"/></w:tcPr>{p(c, bold, 16)}</w:tc>' for c in cells) + "</w:tr>"
    borders = "".join(f'<w:{b} w:val="single" w:sz="4" w:space="0" w:color="888888"/>'
                      for b in ("top", "left", "bottom", "right", "insideH", "insideV"))
    table = (f'<w:tbl><w:tblPr><w:tblW w:w="5000" w:type="pct"/><w:tblBorders>{borders}</w:tblBorders></w:tblPr>'
             + tr(HEAD, True) + "".join(tr([cell_text(j, v) for j, v in enumerate(r)]) for r in rows) + "</w:tbl>")
    body = (p(title, True, 32) + p(sub) + table + p("") + p("Summary", True, 26)
            + "".join(p(f"{l}: {fmt_val(v)}") for l, v in totals)
            + '<w:sectPr><w:pgSz w:w="16838" w:h="11906" w:orient="landscape"/><w:pgMar w:top="720" w:right="720" w:bottom="720" w:left="720" w:header="708" w:footer="708" w:gutter="0"/></w:sectPr>')
    head = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    return zip_bytes({
        "[Content_Types].xml": head + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
        "_rels/.rels": head + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
        "word/document.xml": head + f'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>{body}</w:body></w:document>'})


def make_pdf(title, sub, rows, totals):
    W = [24, 10, 9, 8, 6, 7, 8, 13, 9]
    line = lambda cells: " ".join(str(c)[:W[j]].ljust(W[j]) if j == 0 else str(c).rjust(W[j]) for j, c in enumerate(cells))
    lines = ["#" + title, sub, "", line(HEAD), "-" * (sum(W) + len(W) - 1)]
    lines += [line([cell_text(j, v) for j, v in enumerate(r)]) for r in rows] + ["", "#Summary"]
    lines += [f"{l:<40}{fmt_val(v):>12}" for l, v in totals]
    pages = [lines[i:i + 40] for i in range(0, len(lines), 40)]
    pe = lambda t: t.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"", b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier-Bold >>"]
    kids = []
    for pg in pages:
        n = len(objs) + 1
        kids.append(f"{n} 0 R")
        ops = ["BT", "40 555 Td", "12 TL"] + [
            f"/F2 11 Tf ({pe(l[1:])}) Tj T* /F1 8 Tf" if l.startswith("#") else f"/F1 8 Tf ({pe(l)}) Tj T*"
            for l in pg] + ["ET"]
        stream = "\n".join(ops).encode("latin-1", "replace")
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 842 595] /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {n + 1} 0 R >>".encode())
        objs.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>".encode()
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + "".join(f"{o:010d} 00000 n \n" for o in offs).encode()
    return out + f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()


def make_csv(title, sub, rows, totals):
    out = io.StringIO()
    w = csv.writer(out)
    w.writerows([[title], [sub], [], HEAD] + rows + [[]] + [list(t) for t in totals])
    return out.getvalue().encode("utf-8-sig")  # BOM so Excel shows it correctly


EXPORTS = {"xlsx": (make_xlsx, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
           "docx": (make_docx, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
           "pdf": (make_pdf, "application/pdf"), "csv": (make_csv, "text/csv")}


def open_in_browser(url):
    """Android app only: open the phone's browser, which can download files (the app's own web view cannot)."""
    from jnius import autoclass
    Intent, Uri = autoclass("android.content.Intent"), autoclass("android.net.Uri")
    activity = autoclass("org.kivy.android.PythonActivity").mActivity
    activity.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))


@app.route("/share/<fmt>/<int:cid>")
def share(fmt, cid):
    """Export buttons point here. Laptop/browser: normal download. Android app: download through the browser."""
    if fmt not in EXPORTS:
        abort(404)
    target = url_for("export", fmt=fmt, cid=cid, _external=True)
    if not os.environ.get("ANDROID_PRIVATE"):
        return redirect(target)
    try:
        open_in_browser(target)
        flash("Your browser opened to download the file. Check your Downloads folder.", "success")
    except Exception:
        logging.exception("Could not open the browser for the export")
        flash(f"To download, open Chrome and go to {target} while this app is running.", "warning")
    return redirect(request.referrer or url_for("class_page", cid=cid))


@app.route("/export/<fmt>/<int:cid>")
def export(fmt, cid):
    if fmt not in EXPORTS:
        abort(404)
    maker, mime = EXPORTS[fmt]
    return Response(maker(*report(cid)), mimetype=mime,
                    headers={"Content-Disposition": f"attachment; filename=attendance_report.{fmt}"})


init_db()
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
