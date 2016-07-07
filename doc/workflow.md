# Recipe Developer Workflow

## What are recipes

Recipes are the build scripts in chrome infra. More info is [here](https://github.com/luci/recipes-py).

## Why did CQ reject my change

Your CL will cause downstream recipe expectations to change.  Examine the output
of the tryjob ; there should be steps like `recipe_engine tests`, `build tests`.
The red steps correspond to the repo where, if your change was rolled,
expectations would be changed.

## What should I do

If your change needs a manual patch, because you are doing backwards
incompatible changes which require non machine creatable patches downstream,
[Use a flag](#Use-a-flag).

If your change is dangerous, please [Use a flag](#Use-a-flag).
“Dangerous” means the author, infra people, or reviewers are
scared about this breaking bots. This is ultimately up to your
discretion, but please be thoughtful.

Otherwise, just use the
[Autoroller](#Autoroller).

### Autoroller

The autoroller will automatically land your change. You will have to LGTM the
other CLs which it will create (if there are expectation changes), when it
rolls your change into downstream repos. It is assumed there will be a small
number of these; if there is a large number of them, you should probably [Use a flag](#Use-a-flag).
If your change has expectation changes and you still want the autoroller to
land it, see [I just want to commit a change](#commit).

### Use a flag

This means that you guard your change behind a flag, and disable it by default.
It is your responsibility to then roll the change out manually (e.g. go to users
of the feature and issue CLs to enable the new functionality). Once everything
uses the new functionality:

- change the default flag value to `on-by-default`
- roll that out
- remove the old code and flag.

**Workflow**:

1. Write the new code you want
  to roll out. [Example CL](https://codereview.chromium.org/1999603002)

2. Add a new `Single` value to
  the `recipe_module`’s config which controls the behavior
    - Guard the new behavior behind the configuration value
    - It is acceptable to put a `pragma: no cover` for the if statement which
    triggers the new behavior

3. Commit the change; it should pass all tryjobs and roll safely to all
  dependencies with no effects/expectation changes.

4. Flip users of your recipe module over to the new behavior
    - It is recommended to do this one at a time, starting at the leaves of the
    dependency graph for your recipe module. This makes it much easier to revert
    your change if it breaks something, since you don’t need the roller to pick
    anything up to have the revert take effect.

5. Once everything is flipped over, remove the flag and the old behavior.
    - This step is critical to ensuring that the recipes ecosystem doesn’t
    accumulate a bunch of half-working logic.
    - The infra team reserves the right to nag you about flagged behavior which
    is in the intermediate state for long periods of time.

## I just want to commit my change {#commit}

**If you bypass the [tryjob](https://build.chromium.org/p/tryserver.infra/builders/Recipe%20Roll%20Downstream%20Tester),
and you break other bots, your change may be reverted by a sheriff/trooper, and
you may receive a Post Mortem with your name plastered all over it by the
relevant owners of the code, and/or other interested parties. These recipe
changes can end up breaking the entire chrome infra bot fleet (~4000 machines),
so please be careful. The tryjob is there for a reason.**

Add `Recipe-Tryjob-Bypass-Reason: your reason here`
to the bottom of your CL description (example [here](http://example.com)),
and the tryjob will turn green.

## I want to talk to someone

Email [infra-dev@chromium.org](mailto:infra-dev@chromium.org) (or
[chrome-infra@google.com](mailto:chrome-infra@google.com), if it’s an internal
question). If you _really_ want to talk to a human, you can email
[martiniss@](mailto:martiniss@google.com)
