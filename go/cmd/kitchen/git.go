// Copyright (c) 2015 The Chromium Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

package main

import (
	"fmt"
	"os"
	"os/exec"
	"strings"

	"github.com/golang/go/src/path/filepath"
	"github.com/luci/luci-go/common/ctxcmd"
	"golang.org/x/net/context"
)

// clone clones a Git repo.
func clone(c context.Context, repoUrl, workdir string) error {
	return runGit(c, "", "clone", repoUrl, workdir)
}

// cloneOrFetch ensures that workdir is a git directory
// with origin pointing to repoURL
// and containing the latest commit of the master branch.
// If workdir is a non-empty non-git directory
// or if it is a git directory with a different repository URL
// cloneOrFetch returns an error.
func cloneOrFetch(c context.Context, workdir, repoURL string) error {
	if _, err := os.Stat(workdir); os.IsNotExist(err) {
		return clone(c, repoURL, workdir)
	}

	// Is it a Git repo?
	if err := git(workdir, "rev-parse").Run(c); err != nil {
		if _, ok := err.(*exec.ExitError); !ok {
			return err
		}
		// It is not a Git repo.
		dir, err := os.Open(workdir)
		if err != nil {
			return fmt.Errorf("cannot open workdir %q: %s", workdir, err)
		}
		files, err := dir.Readdir(1)
		dir.Close()
		if err != nil {
			return fmt.Errorf("cannot read workdir %q: %s", workdir, err)
		}
		if len(files) > 0 {
			return fmt.Errorf("workdir %q is a non-git non-empty directory.", workdir)
		}
		return clone(c, repoURL, workdir)
	}

	// Is origin's URL same?
	originUrlBytes, err := git(workdir, "config", "remote.origin.url").Output()
	if err != nil {
		return err
	}
	originUrl := strings.TrimSpace(string(originUrlBytes))
	if originUrl != repoURL {
		return fmt.Errorf("workdir %q is a git repository with a different origin url: %q != %q", workdir, originUrl, repoURL)
	}

	return runGit(c, workdir, "fetch", "origin")
}

// checkoutRepository checks out repository at revision to workdir.
// If workdir doesn't exist, clones the repo, otherwise tries to fetch.
func checkoutRepository(c context.Context, workdir, repository, revision string) error {
	if err := cloneOrFetch(c, workdir, repository); err != nil {
		return err
	}

	if revision == "" {
		revision = "FETCH_HEAD"
	}
	if revision == "FETCH_HEAD" {
		// FETCH_HEAD may not exist if repo was just cloned.
		ref_path := filepath.Join(workdir, ".git", revision)
		if _, err := os.Stat(ref_path); os.IsNotExist(err) {
			// Skip checkout.
			return nil
		}
	}
	return runGit(c, workdir, "checkout", revision)
}

// git returns an *exec.Cmd for a git command, with Stderr redirected.
func git(workDir string, args ...string) *ctxcmd.CtxCmd {
	cmd := exec.Command("git", args...)
	if workDir != "" {
		cmd.Dir = workDir
	}
	cmd.Stderr = os.Stderr
	return &ctxcmd.CtxCmd{Cmd: cmd}
}

// runGit prints the git command, runs it, redirects Stdout and Stderr and returns an error.
func runGit(c context.Context, workDir string, args ...string) error {
	cmd := git(workDir, args...)
	if workDir != "" {
		absWorkDir, err := filepath.Abs(workDir)
		if err != nil {
			return err
		}
		fmt.Print(absWorkDir)
	}
	fmt.Printf("$ %s\n", strings.Join(cmd.Args, " "))
	cmd.Stdout = os.Stdout
	return cmd.Run(c)
}
