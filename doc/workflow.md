# Recipe Developer Workflow

## What are recipes

Recipes are the build scripts in chrome infra. More info is [here](../README.md).

## Why did CQ reject my change

A common reason is that your CL may cause downstream recipe expectations to
change. Examine the output of the tryjob ; there should be steps like
`recipe_engine tests`, `build tests`. The red steps correspond to the repo
where, if your change was rolled, expectations would be changed.

## What should I do

If your change needs a manual patch, because you are doing backwards
incompatible changes which require non machine creatable patches downstream,
[Use a flag](#Use-a-flag).

If your change is dangerous, please [Use a flag](#Use-a-flag). "Dangerous"
means the author, infra people, or reviewers are scared about this breaking
bots. This is ultimately up to your discretion, but please be thoughtful.

Otherwise, just use the
[Autoroller](#Autoroller).

### Autoroller

*** note
For cross-repo dependencies, please check [cross repo](./cross_repo.md).
***

When downstream repos depend on your recipe, the [autorollers], controlled via
these [config options], automatically loads your change and makes CLs on the
downstream repos.
The autorollers also understands the cross-repo dependency graph, and
propgates changes from upstream to downstream sequentially.

Rollout CLs have 2 types:
- `trivial`, when the CL run the tests without any errors.
- `nontrivial`, when the CL changes the expectations JSON files, but otherwise
   runs the tests successfully.

See [config options] for details.

The review processes are different as follows:
- When the rollout CL is `trivial`, the autoroller submits the CL without
  owner approvals.
- When the rollout CL is `nontrivial`, a repo owner needs to approve and submit
  the CL.

[autorollers]: https://ci.chromium.org/ui/p/infra-internal/g/recipe-rollers/builders
[config options]: https://crsrc.org/i/recipes-py/recipe_engine/recipes_cfg.proto?q=%22message%20AutorollRecipeOptions%22

If there is a large number of recipe changes, you should probably
[Use a flag](#Use-a-flag).
If your change has expectation changes and you still want the autoroller to
land it, see [I just want to commit a change](#commit).

### Use a flag

<!--
TODO(yiwzhang): Update this section:
Consider changing this to mention using input properties, and change the
workflow to use new protobuf based property if needed instead of the legacy
style (i.e. the `Single` value mentioned below)
-->

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

### Rollback

*** note
For cross-repo dependencies, please check [cross repo](./cross_repo.md).
***

After you revert an upstream recipe change, the autoroller also makes CLs to
rollout the revert to the downstream repos.

- When the rollout CL is `trivial`, the rollback is propagated without owner
approvals.
- When the rollout CL is `nontrivial`, the rollback requires owner approvals.

These processes may not be efficient to rollback production quicikly because:

- The rollout CLs may take a long time in CQ.
- The rollout CLs may fail at the downstream CQ.
- The rollout CLs may wait for long time to get owner approvals.

For fast rollback, we have some options.

#### Bypass intermediate repos

You can bypass intermediate repos, and apply the rollback to the affected repos
directly.

1. Revert your recipe in the upstream repo.
1. Update the [revision] in the downstream `recipes.cfg` to include the revert
   change.
1. Wait for the autoroller to catchup other recipe dependencies.

[revision]: https://crsrc.org/i/recipes-py/recipe_engine/recipes_cfg.proto?q=revision

#### Disable autoroller

You can revert the rollout CLs on the affected repos directly. But you need to
stop the autoroller, otherwise it will reland the problematic CL.

1. Add [disable_reason] to the downstream `recipes.cfg`.
1. Revert the rollout CL on the affected repos.
1. Revert your recipe in the upstream repo.
1. Wait for the autoroller of other repos to propagte the revert.
1. Remove the `disable_reason` from `recipes.cfg`.

[disable_reason]: https://crsrc.org/i/recipes-py/recipe_engine/recipes_cfg.proto;l=82?q=disable_reason

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
