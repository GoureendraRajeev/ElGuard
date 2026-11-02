import os
import sys
import webbrowser
from threading import Timer

if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "elguard_site.settings")

    if "runserver" in sys.argv:
        Timer(1.5, lambda: webbrowser.get(
            'C:/Program Files/Google/Chrome/Application/chrome.exe %s'
        ).open("http://127.0.0.1:8000/")).start()

    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)