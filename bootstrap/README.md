## bootstrap.py (a.k.a. "I just want a working recipes-py")

Run

    ./bootstrap/bootstrap.py --deps_file bootstrap/deps.pyl ENV

This creates a virtualenv called `ENV` with all the deps
contained in `bootstrap/deps.pyl`.

For more information, see the infra.git bootstrap [README](https://chromium.googlesource.com/infra/infra/+/master/bootstrap/README.md)
