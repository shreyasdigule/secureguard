import os

files = ['dashboard_qt.py', 'main_qt.py', 'dashboard_qt_new.py', 'evidence_tab.py']
for f in files:
    path = os.path.join('.', f)
    if os.path.exists(path):
        with open(path) as fh:
            content = fh.read()
        psid = content.count('PySide6')
        pq = content.count('PySide6')
        print(f'{f}: PySide6={psid}, PySide6={pq}')
    else:
        print(f'{f}: not found')
