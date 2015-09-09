#!/bin/sh
# to be run from a clone of https://chromium.googlesource.com/chromium/tools/build.git

# This first one rewrites the parent information, fixes the author email
# addresses, and prunes out large swaths of the committed repos, to make the
# tree-filter below faster.
#
# This should be processing just over 9000 commits.
git --no-replace-objects filter-branch -f --prune-empty --index-filter '. /FILTERDIR/index_filter.sh' --env-filter '. /FILTERDIR/env_filter.sh' --parent-filter '. /FILTERDIR/parent_filter.sh' -- 70d6a3c2d97de862e9f678745d0763b14d385c18~..49d75fea5885998dc340c2a6fdf65b2f4312eee4

# This saves the previously filtered history to filtered1, in case you want to
# run the tree-filter below multiple times (e.g. in case you're modifying the
# tree filter to get a better result).
git update-ref refs/heads/filtered1 HEAD

# /STAGING is used to mv files during the tree-filter phase. Since this is
# dangerous, it's commented out.
#    rm -rf /STAGING
#    mkdir /STAGING
#    chown $USER /STAGING

# Actually rewrite all the trees. This should be processing ~5000 commits.
git --no-replace-objects filter-branch -f --prune-empty --tree-filter '. /FILTERDIR/tree_filter.sh 2> /dev/null'
