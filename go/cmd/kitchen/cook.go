// Copyright (c) 2013-2015 The Chromium Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

package main

import (
	"fmt"
	"net/url"
	"os"
	"os/exec"
	"path"
	"strings"
	"syscall"

	"github.com/golang/go/src/io/ioutil"
	"github.com/luci/luci-go/common/ctxcmd"
	"github.com/maruel/subcommands"
	"golang.org/x/net/context"
)

const BOOTSTRAP_STEP_NAME = "recipe bootstrap"

// cmdCook checks out a repository at a revision and runs a recipe.
var cmdCook = &subcommands.Command{
	UsageLine: "cook -repository <repository URL> -revision <revision> -recipe <recipe>",
	ShortDesc: "Checks out a repository and runs a recipe.",
	LongDesc:  "Clones or fetches a repository, checks out a revision and runs a recipe",
	CommandRun: func() subcommands.CommandRun {
		var c cookRun
		fs := &c.Flags
		fs.StringVar(&c.RepositoryURL, "repository", "", "URL of a git repository to fetch")
		fs.StringVar(
			&c.Revision,
			"revision",
			"FETCH_HEAD",
			"Git commit hash to check out.")
		fs.StringVar(&c.Recipe, "recipe", "<recipe>", "Name of the recipe to run")
		fs.StringVar(
			&c.CheckoutDir,
			"checkout-dir",
			"",
			"The directory to check out the repository to. "+
				"Defaults to ./<repo name>, where <repo name> is the last component of -repository.")
		fs.StringVar(
			&c.Workdir,
			"workdir",
			"",
			"The working directory for recipe execution. Defaults to a temp dir.")
		fs.StringVar(&c.Properties, "properties", "", "A json string containing the properties")
		fs.StringVar(&c.PropertiesFile, "properties-file", "", "A file containing a json blob of properties")
		fs.StringVar(
			&c.OutputResultJsonFile,
			"output-result-json",
			"",
			"The file to write the JSON serialized returned value of the recipe to")
		return &c
	},
}

type cookRun struct {
	subcommands.CommandRunBase

	RepositoryURL        string
	Revision             string
	Recipe               string
	CheckoutDir          string
	Workdir              string
	Properties           string
	PropertiesFile       string
	OutputResultJsonFile string
}

func (c *cookRun) validateFlags() error {
	// Validate Repository.
	if c.RepositoryURL == "" {
		return fmt.Errorf("-repository is required")
	}
	repoURL, err := url.Parse(c.RepositoryURL)
	if err != nil {
		return fmt.Errorf("invalid repository %q: %s", repoURL, err)
	}
	repoName := path.Base(repoURL.Path)
	if repoName == "" {
		return fmt.Errorf("invalid repository %q: no path", repoURL)
	}

	// Validate Recipe.
	if c.Recipe == "" {
		return fmt.Errorf("-recipe is required")
	}

	// Fix CheckoutDir.
	if c.CheckoutDir == "" {
		c.CheckoutDir = repoName
	}
	return nil
}

// run checks out a repo, runs a recipe and returns exit code.
func (c *cookRun) run(ctx context.Context) (recipeExitCode int, err error) {
	if err = checkoutRepository(ctx, c.CheckoutDir, c.RepositoryURL, c.Revision); err != nil {
		return 0, err
	}

	if c.Workdir == "" {
		var tempWorkdir string
		if tempWorkdir, err = ioutil.TempDir("", "kitchen-"); err != nil {
			return 0, err
		}
		defer os.RemoveAll(tempWorkdir)
		c.Workdir = tempWorkdir
	}

	recipe := recipeRun{
		repositoryPath:       c.CheckoutDir,
		workDir:              c.Workdir,
		recipe:               c.Recipe,
		propertiesJSON:       c.Properties,
		propertiesFile:       c.PropertiesFile,
		outputResultJSONFile: c.OutputResultJsonFile,
	}
	recipeCmd, err := recipe.Command()
	if err != nil {
		return 0, err
	}

	recipeCtxCmd := ctxcmd.CtxCmd{Cmd: recipeCmd}
	switch err := recipeCtxCmd.Run(ctx).(type) {
	case *exec.ExitError:
		switch sys := err.Sys().(type) {
		case syscall.WaitStatus:
			return sys.ExitStatus(), nil
		default:
			return 1, nil
		}

	case nil:
		return 0, nil

	default:
		if err == recipeCtxCmd.ProcessError {
			err = fmt.Errorf("failed to run recipe: %s", err)
		}
		return 0, err
	}
}

func (c *cookRun) Run(a subcommands.Application, args []string) (exitCode int) {
	app := a.(*App)
	var err error
	if len(args) != 0 {
		err = fmt.Errorf("unexpected arguments %v\n", args)
	} else {
		err = c.validateFlags()
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		c.Flags.Usage()
		return 1
	}

	annotate("SEED_STEP", BOOTSTRAP_STEP_NAME)
	annotate("STEP_CURSOR", BOOTSTRAP_STEP_NAME)
	annotate("STEP_STARTED")
	recipeExitCode, err := c.run(app.Context)
	annotate("STEP_CURSOR", BOOTSTRAP_STEP_NAME)
	if err != nil {
		if err != context.Canceled {
			fmt.Fprintln(os.Stderr, err)
		}
		return -1
	}
	annotate("STEP_CLOSED")
	return recipeExitCode
}

func annotate(args ...string) {
	fmt.Printf("@@@%s@@@\n", strings.Join(args, "@"))
}
