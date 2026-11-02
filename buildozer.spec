[app]
title = Attendance Register
icon.filename = %(source.dir)s/icon.png
package.name = attendanceregister
package.domain = org.attendance
source.dir = .
source.include_exts = py,html,css,png
source.exclude_dirs = .github,bin,dist,build,__pycache__,.buildozer
version = 1.0
requirements = python3,sqlite3,flask,werkzeug,jinja2,markupsafe,itsdangerous,click,blinker,pyjnius
orientation = portrait
android.permissions = INTERNET
android.api = 33
android.minapi = 24
android.archs = arm64-v8a, armeabi-v7a
android.accept_sdk_license = True
p4a.bootstrap = webview
p4a.port = 5000
p4a.branch = v2024.01.21
android.ndk = 25b

[buildozer]
log_level = 2
warn_on_root = 1
