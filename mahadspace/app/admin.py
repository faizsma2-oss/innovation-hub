"""Administrator commands, run from the mahadspace folder:

    python -m app.admin users                      list accounts and whether they're verified
    python -m app.admin verify someone@example.com allow an account to sign in
    python -m app.admin unverify someone@example.com
"""
import sys

from . import db


def main(argv: list[str]) -> int:
    db.init()
    if not argv or argv[0] not in ("users", "verify", "unverify"):
        print(__doc__)
        return 1
    with db.connect() as conn:
        if argv[0] == "users":
            for row in conn.execute("SELECT email, display_name, verified, created_at FROM users ORDER BY id"):
                print(f"{row['email']:40} {'verified' if row['verified'] else 'NOT verified':13} {row['display_name']}")
            return 0
        if len(argv) < 2:
            print("Give the account's email address.")
            return 1
        changed = conn.execute("UPDATE users SET verified = ? WHERE email = ?",
                               (int(argv[0] == "verify"), argv[1].strip().lower())).rowcount
    print(f"{argv[1]} {'verified' if argv[0] == 'verify' else 'unverified'}." if changed else f"No account {argv[1]}.")
    return 0 if changed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
