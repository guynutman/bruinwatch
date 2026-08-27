def build_notify_callback() -> NotifyCallback:
    """Build the platform-appropriate alert function.

    Returns a closure so Watcher can call it without knowing what it does.
    Every platform-specific branch in the program lives inside here.
    """
    system = platform.system()

    def play_sound() -> None:
        """Best-effort audible alert; falls back to the terminal bell."""
        try:
            if system == "Darwin":
                subprocess.run(["afplay", "/System/Library/Sounds/Glass.aiff"],
                               check=False, timeout=5)
                return
            if system == "Windows":
                import winsound

                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
                return
            if system == "Linux":
                subprocess.run(
                    ["paplay", "/usr/share/sounds/freedesktop/stereo/bell.oga"],
                    check=False, timeout=5,
                )
                return
        except (OSError, subprocess.SubprocessError, ImportError):
            pass  # no audio device, or the tool is missing -- fall through

        print("\a", end="", flush=True)

    def notify(course_name: str, seats: int, section_label: str) -> None:
        message = f"{section_label}: {seats} seat(s) open"
        print(f"  >>> {course_name} - {message}")

        if desktop_notify is not None:
            try:
                desktop_notify.notify(
                    title="BruinWatch - Seat Available!",
                    message=f"{course_name}\n{message}",
                    app_name="BruinWatch",
                    timeout=10,
                )
            except Exception:
                pass  # a failed popup must never kill the poll loop

        play_sound()

    return notify

def main() -> None:
    print("=" * 60)                          # 1. banner
    print("  BruinWatch - UCLA course seat monitor")

    client = SOCClient()                     # 2. open HTTP session, get cookies

    term_cd, term_name = choose_term(client) # 3. prompt: which term?

    courses = choose_courses(client, term_cd)# 4. prompt: which courses? validate each

    print(f"  Monitoring {len(courses)} course(s)...")   # 5. summary

    Watcher(                                 # 6. build the watcher...
        client,
        courses,
        notify=build_notify_callback(),
    ).run()                                  # ...and hand it control forever


if __name__ == "__main__": main()