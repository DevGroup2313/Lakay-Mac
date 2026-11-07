#!/usr/bin/env python3
# LAKAY  |  Copyright (c) 2026 Yannie D. Forest. All rights reserved.
# NO LICENCE IS GRANTED. See LICENCE.txt.
"""Puts a finished app where the owner's other apps keep theirs.

    python release/publish.py <file> <label> [note]

1. The Releases page. Each repository has one release, "Lakay for <device> (latest build)" (tag "latest"), as
   Ingenium's repositories have. The file replaces the older copy of the same name. The notes list only this
   repository's files: what each one is, how to install it, its build and its SHA-256.
2. The builds/ folder. The same file is committed to builds/ on the branch it was built from, as Inkwell's
   repositories keep theirs, so the ready-made app can be downloaded from the repository's front page. That
   commit carries [skip ci], and it is made only while the branch still holds the page this file was built from.

Run by the GitHub workflows, with the workflow's own token (the gh command and git).
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TAG = "latest"

# The device each repository serves, its release title, and its own guide.
DEVICES = [
    ("Lakay-Mac", "Mac", "READ ME FIRST (Mac).txt"),
    ("Lakay-Apps", "iPhone, iPad and Fire", "READ ME FIRST - IPHONE AND IPAD.txt and READ ME FIRST - FIRE TABLET.txt"),
    ("Lakay-Windows", "Windows", "READ ME FIRST (Windows).txt"),
]

# Every file Lakay publishes, in the order the notes list them: what it is, and how to install it.
FILES = [
    ("Lakay-Windows-Setup.exe",
     "**Start here** for Windows 10 and 11: the installer. The PC needs nothing else (no Python, no administrator password).",
     "Double-click it. It installs Lakay for you only and puts it in the Start menu. If Edge says the file is not commonly "
     "downloaded: the three dots, Keep, Show more, Keep anyway. If Windows shows \"Windows protected your PC\": More info, "
     "Run anyway. To update, run a newer one; the books stay."),
    ("Lakay-Mac-Apple-Silicon.zip",
     "**Start here** for Macs with Apple silicon (M1 and later, such as the Mac mini).",
     "Unzip it and drag Lakay to Applications. The first time, open System Settings, Privacy and Security, and choose "
     "Open Anyway. To update, replace the old Lakay; the books stay."),
    ("Lakay-Mac-Intel.zip",
     "**Start here** for Macs with an Intel processor (such as a 2019 MacBook Pro).",
     "As for Apple silicon."),
    ("Lakay-iPhone-iPad.ipa",
     "**Start here** for iPhone and iPad: one file for both.",
     "On a computer, open Sideloadly, connect the iPhone or iPad with its cable, drag this file in, type your Apple ID and "
     "press Start. Tapping the file on the iPhone or iPad installs nothing. With a free Apple ID, install it again this way "
     "every 7 days; the books stay."),
    ("Lakay-Android-Fire.apk",
     "**Start here** for the Fire tablet and other Android tablets.",
     "Copy it into the tablet's Download folder (by cable, or download it on the tablet). On the tablet, open Files, tap "
     "it, then Install. The first time, allow apps from unknown sources."),
]
KNOWN = [f[0] for f in FILES]
# Files Lakay no longer publishes: they leave the Releases page, so an old copy is never taken for a new one.
RETIRED = ["Lakay-Standalone-Page.zip", "Lakay-iPhone-iPad-unsigned.ipa"]
BOT = ("github-actions[bot]", "41898282+github-actions[bot]@users.noreply.github.com")


def gh(*args, capture=False):
    return subprocess.run(["gh", *args], capture_output=capture, text=True)


def git(*args, env=None):
    return subprocess.run(["git", *args], capture_output=True, text=True, cwd=ROOT, env=env)


def git_out(*args, env=None):
    r = git(*args, env=env)
    if r.returncode != 0:
        raise RuntimeError("git %s: %s" % (" ".join(args[:2]), (r.stderr or "").strip()[:300]))
    return r.stdout.strip()


def device():
    repo = os.environ.get("GITHUB_REPOSITORY", "").lower()
    for key, name, guide in DEVICES:
        if key.lower() in repo:
            return name, guide
    return DEVICES[-1][1], DEVICES[-1][2]


def notes(name, guide, lines, assets):
    """The release page's words: a table of this repository's files, then one line for each file."""
    out = ["Lakay for %s. Lakay is the store's own app: it works with no connection, and it keeps its own sealed "
           "books on each device." % name, "",
           "| File | What it is | How to install |", "| --- | --- | --- |"]
    for fname, what, how in FILES:
        if fname in assets:
            out.append("| **%s** | %s | %s |" % (fname, what, how))
    for fname in sorted(assets):
        if fname not in KNOWN:
            out.append("| %s | | |" % fname)
    out += ["", "The same files are in this repository's **builds** folder. %s beside them %s how to install, update and "
            "keep the books safe." % (guide, "say" if " and " in guide else "says"), "",
            "**Each file** (the build number also shows in Lakay's About):"]
    order = KNOWN + [f for f in sorted(lines) if f not in KNOWN]
    out += [lines[f] for f in order if f in lines and f in assets]
    return "\n".join(out) + "\n"


def to_builds(path, build, page_sha):
    """Commits the file to builds/ on the branch it was built from, without touching the working folder."""
    branch = os.environ.get("GITHUB_REF_NAME", "")
    if not branch or os.environ.get("GITHUB_REF_TYPE", "branch") != "branch":
        print("Not built from a branch: builds/ is left as it is.")
        return
    fname = os.path.basename(path)
    env = dict(os.environ, GIT_AUTHOR_NAME=BOT[0], GIT_AUTHOR_EMAIL=BOT[1], GIT_COMMITTER_NAME=BOT[0],
               GIT_COMMITTER_EMAIL=BOT[1])
    index = os.path.join(tempfile.mkdtemp(), "index")
    for attempt in range(5):
        if attempt:
            time.sleep(6 * attempt)
        try:
            if git("fetch", "-q", "--depth=1", "origin", branch).returncode != 0:
                print("git fetch failed; trying again.")
                continue
            tip = git_out("rev-parse", "FETCH_HEAD")
            # Only while the branch still carries the page and the build number this file was made from: a newer
            # build will put its own file here.
            tip_sha = git_out("show", tip + ":app/Lakay.html.sha256").split()[0]
            tip_build = int(json.loads(git_out("show", tip + ":build.json"))["build"])
            if tip_sha != page_sha or tip_build != build:
                print("The branch already holds a newer build; builds/ waits for that one.")
                return
            blob = git_out("hash-object", "-w", "--no-filters", path)
            ienv = dict(env, GIT_INDEX_FILE=index)
            git_out("read-tree", tip, env=ienv)
            git_out("update-index", "--add", "--cacheinfo", "100644,%s,builds/%s" % (blob, fname), env=ienv)
            tree = git_out("write-tree", env=ienv)
            if tree == git_out("rev-parse", tip + "^{tree}"):
                print("builds/%s already holds this file." % fname)
                return
            commit = git_out("commit-tree", tree, "-p", tip, "-m",
                             "builds/%s: Lakay Build %d, ready to download [skip ci]" % (fname, build), env=env)
            r = git("push", "-q", "origin", "%s:refs/heads/%s" % (commit, branch))
            if r.returncode == 0:
                print("builds/%s is on %s (commit %s)." % (fname, branch, commit[:7]))
                summary = os.environ.get("GITHUB_STEP_SUMMARY")
                if summary:
                    with open(summary, "a", encoding="utf-8") as fh:
                        fh.write("* builds/%s committed to %s\n" % (fname, branch))
                return
            print("git push was refused (%s); trying again." % (r.stderr or "").strip()[:200])
        except Exception as e:
            print("builds/: %s; trying again." % e)
    print("::warning::builds/%s could not be committed. The file is on the Releases page." % fname)


def main():
    path, label = sys.argv[1], sys.argv[2]
    note = sys.argv[3] if len(sys.argv) > 3 else ""
    with open(os.path.join(ROOT, "build.json"), encoding="utf-8") as fh:
        info = json.load(fh)
    build = int(info["build"])
    date = str(info.get("date", ""))
    sha = os.environ.get("GITHUB_SHA", "")
    commit = sha[:7]
    name, guide = device()
    title = "Lakay for %s (latest build)" % name
    fname = os.path.basename(path)
    with open(path, "rb") as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()
    with open(os.path.join(ROOT, "app", "Lakay.html.sha256"), encoding="utf-8") as fh:
        page_sha = fh.read().split()[0]
    tmp = tempfile.mkdtemp()

    # The release's tag follows the newest build, so its "Source code" files are that build's.
    if sha and git("tag", "-f", TAG, sha).returncode == 0:
        if git("push", "-f", "origin", "refs/tags/" + TAG).returncode != 0:
            print("(the tag could not be moved; the release stays where it is, and its files are still replaced)")
    if gh("release", "view", TAG, capture=True).returncode != 0:
        gh("release", "create", TAG, "--target", sha or "HEAD", "--title", title, "--notes", "Building...", "--latest")

    for wait in (0, 15, 30, 60):
        time.sleep(wait)
        if gh("release", "upload", TAG, path, "--clobber").returncode == 0:
            break
        print("GitHub did not accept the file; trying again.")
    else:
        sys.exit("GitHub did not accept %s after four tries. If an error above says 403, the cure is "
                 "Settings, Actions, General, Workflow permissions: Read and write." % fname)

    # Files of the app's former name (Emporium) and files Lakay no longer makes leave the page.
    r = gh("release", "view", TAG, "--json", "assets", "-q", ".assets[].name", capture=True)
    assets = set(r.stdout.split()) if r.returncode == 0 else set()
    for asset in sorted(assets):
        if asset.startswith("Emporium-") or asset in RETIRED:
            if gh("release", "delete-asset", TAG, asset, "-y").returncode == 0:
                assets.discard(asset)
                print("Removed %s from the Releases page: Lakay no longer makes it." % asset)
    assets.add(fname)

    # One line per file, kept from the page as it was, this file's replaced.
    line = "- %s: Build %d (%s), from `%s`.%s SHA-256 `%s`" % (fname, build, date, commit, (" " + note[0].upper() + note[1:] + ".") if note else "", digest)
    lines = {}
    for _ in range(4):
        r = gh("release", "view", TAG, "--json", "body", "-q", ".body", capture=True)
        if r.returncode == 0:
            for x in r.stdout.splitlines():
                x = x.rstrip()
                if x.startswith("- ") and ": Build " in x:
                    lines[x[2:].split(":", 1)[0]] = x
        lines[fname] = line
        nf = os.path.join(tmp, "notes.md")
        with open(nf, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(notes(name, guide, lines, assets))
        if gh("release", "edit", TAG, "--title", title, "--notes-file", nf, "--latest").returncode == 0:
            break
        time.sleep(5)

    r = gh("release", "list", "--limit", "50", "--json", "tagName", "-q", ".[].tagName", capture=True)
    for old_tag in (r.stdout.split() if r.returncode == 0 else []):
        if old_tag.startswith("build-"):
            gh("release", "delete", old_tag, "--cleanup-tag", "-y")
            print("Removed the older page %s: everything is on %s now." % (old_tag, TAG))

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("### %s: %s\n\n* [%s](https://github.com/%s/releases/latest/download/%s)\n* SHA-256 %s\n"
                     % (title, label, fname, os.environ.get("GITHUB_REPOSITORY", ""), fname, digest))
    print("Published %s on %s (SHA-256 %s)" % (fname, title, digest))

    to_builds(path, build, page_sha)


if __name__ == "__main__":
    main()
