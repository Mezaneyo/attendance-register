# Attendance Register
A simple attendance system. Developer: **Chisomo Pen Chitembeya**. Works in the browser, as a Windows `.exe` and as an Android `.apk`.
Python 3 + Flask + SQLite. The design uses its own CSS (no external libraries), so it also works offline.

## How to use it
1. **Create a class or group** (for example "Form 3A" or "Choir").
2. **Add members**: type one name per line. An ID can follow a comma: `Mary Banda, 2024/001`.
3. **Take attendance**: pick the date (and an optional title). Everyone starts as Present; tap **L**ate, **A**bsent or **E**xcused for the others, then Save.
4. See each member's **attendance %**. Anyone below the minimum (Settings, default 75%) is shown in red.
5. **Export** the report to Excel, PDF, Word or CSV.

Attendance % = (Present + Late) / (Present + Late + Absent) x 100. Excused sessions, and sessions where the member was not marked, are not counted.

## The flow in the code
```
tap a button -> route in app.py -> checks the input -> q() reads/writes attendance.db
            -> class_data() does the maths -> a template in templates/ shows the page
```
| File | Job |
|---|---|
| `app.py` | Database, attendance maths (`class_data`), all pages, exports |
| `main.py` / `desktop.py` | Start-up for Android / Windows `.exe` |
| `templates/` | `base.html` layout, `index.html` classes, `class.html` one class, `take.html` marking page, `edit_member.html`, `settings.html`, `error.html` |
| `attendance.db` / `attendance.log` | Saved data / crash details (full traceback) |

Tables: `classes`, `members` (class_id), `sessions` (class_id, day, title), `marks` (session_id, member_id, status), `settings`.

## Run
    pip install flask
    python app.py          # then open http://127.0.0.1:5000

## Debugging
- Errors appear in the terminal and in `attendance.log`: `tail -n 40 attendance.log`
- Read the traceback from the bottom: the last line says what went wrong, the line above says where.
- `python -m py_compile app.py` checks the syntax. `git diff` shows what was changed. Start with clean data: stop the app, delete `attendance.db`, start again.
- Browser pop-ups like `confirm()` do not work in the Android app, so delete buttons use a two-tap "Sure?".

## Build the .exe and .apk in the cloud
Push this folder to GitHub. The **Actions** tab builds both (the APK takes 10 to 15 minutes). Download them from **Artifacts**.
Keep these build settings: `buildozer==1.5.0`, Java 17, `p4a.branch`, `android.ndk`, and `sqlite3` + `pyjnius` in `requirements`.
