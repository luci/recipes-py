# kitchen

kitchen is a command line tool that can fetch a git _repository_, checkout at a
specific _revision_ and run a named _recipe_.
We call these three parameters _RRR_.

The only kitchen's runtime dependencies are git and python.
They must be in `$PATH.` 

Although this repository is called `recipe-py`, kitchen is in Go to simplify 
deployment.

## isolation

isolate_kitchen.py compiles kitchen for a variety of operating systems and
architectures and isolates them.
It automatically chooses a correct binary for the current platform.
Then the isolate can be ran with extra args, e.g.

    cook -repository https://chromium.googlesource.com/chromium/tools/build \
        -revision deadbeef \
        -recipe myrecipe \
        -properties '{"mastername": "client.v8", "slavename": "vm1-m1"}'
