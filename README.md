# About
Showcaser is a GitHup App that lets you showcase the contents of a repository into another repository - maybe one that has a [GitHub Pages](https://pages.github.com/) environment active, so that the rest of the world can see it on the world wide web!

Showcaser essentially just copies the contents of the repository you want to showcase - the 'originating repo' - to a directory in a public-facing repo - the 'showcase repo'. Showcaser is easily installed and is configured by writing a simple `.showcase` file in the root directory of the directories you install it in.

You can install this app on your own repositories from it's GitHub Apps page [here](https://github.com/apps/showcaser).

# Warning

Showcaser is still in alpha development, and almost certantly contains bugs or unexpected behaviour. This app has the permission & capability to delete EVERY SINGLE FILE from the repos you install it in. Showcaser is provided without any warantee or guarantee. If I were you, I wouldn't install this app unless you knew @Esouder really well and REALLY trusted them not to make a mistake which wipes the contents of your github repos. 

# Setup

## Install Showcaser

You can install showcaser from it's Github Apps page [here](https://github.com/apps/showcaser).

Follow all the instructions on Github - there aren't too many. You'll need to give the app a few permissions: 

* **Read and write access to code** (i.e. repo contents) is required to copy files from your originating repo(s) to your showcase repo(s)
* **Read and write access to issues** is needed so that Showcaser can tell you what behaviour to expect when creating a pull request by commenting on your pull requests. And also to send you a "thanks for installing" message
* **Read and write access to pull requests** is required in order to know when you are making pull requests that Showcaser should act on, and to merge Showacaser's updates into your showcase repo.
* **Read access to metadata** is a supporting permission required by the GitHub API for the above permissions. This permission does not access any sensitive data, and is a default permission for all GitHub Apps.

It is only required (and is reccomended) to only install Showcaser on the Repos you intend to use it on - e.g. only on your originating and showcase repos. There's no need to select 'All Repositories' - just add it to the ones you need it in. I can't stop you from installing it everywhere ([I'm a sign, not a cop](https://i.imgur.com/mSHi8.jpg)), but doing so would just be kinda inefficient, waste power at some nameless datacenter, and eat up all my free dyno hours :(.

## Create and connfigure `.showcase` files

For each originating and showcase repo, create a file called `.showcase`. `.showcase` is really just a unique name that you are pretty unlikely to have already used in your project, but it's really just a bog-standard JSON file. You'll need to add a few things to it:

| Key | Data |
| --- | --- |
|`showcaseEnable `| `true` if you actually, you know, want the app to run on this repo. `false` if you want to disable running showcaser on this repo. But in the long term, it's better to just uninstall the app from this repo and remove the `.showcase` file.|
|`"isShowcaseRepo"` | `true` if this is the repo that your stuff will be displayed in. Otherwise `false`.|
|`includedDirectories`| A list e.g. `["/src/","/images/"]` of all the directories you want showcaser to copy. Include a single `/` entry if you want to copy the root directory, e.g. `["/"]`. This needs both a leading and trailing slash. *Only if `isShowcaseRepo` is `false`.*|
|`excludedFiles`|Any files you don't want showcaser to copy. Path must be from repo root directory, and no regex matching (e.g. `*.txt` or anything). Sorry. Do not include a leading slash. *Only if `isShowcaseRepo` is `false`.*|

Here's an example of what a `.showcase` file might look like:
```
{
    "showcaseRepo" : "Test-repo-2",
    "includedDirectories" : [
        "/src"
    ],
    "excludedFiles" : [
        ".gitignore",
        "src/secret_launch_codes.txt"
    ]
}
```
# Usage

Once you've set it up, you can pretty much ignore it; Showcaser functions basically on it's own. There are no special steps you need to take.

When you create a pull request in a originating repo, Showcaser will comment on that source request to tell you that your changes from the pull request will be reflected in a showcase repo.

When you merge a pull request in an originating repo, Showcaser will update a directory in the showcase repo with the changes. 

Note that Showcaser will not function on changes that aren't made in a pull request - so, for example, if you merge a change in a originating repo directly into your default branch from the GitHub website, that change will not be reflected in the showcase Repo.

# Support

Lol good luck with that.

You can create an issue in the issues tab, and maybe that'll get you some help though. No promises.

The issues tab also shows what I'm working on adding to this at the moment. 
