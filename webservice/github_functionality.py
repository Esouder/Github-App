import asyncio
import base64
import json
import os
import sys
import traceback
import urllib.request
from webservice.__main__ import collect_files_recursive

import aiohttp
import cachetools
from aiohttp import web
from gidgethub import aiohttp as gh_aiohttp
from gidgethub import apps, routing, sansio


def appext(origlist, data):
    """Short for "append/extend". This takes a list and some single item or
    iterable. If it's an item, it uses the .append() method to add it to the end
    of the list, and if it's a list, it uses the .extend() method to add it to
    the end of the list. It then returns the list.

    >>>appext(["apple","orange"],"pear")

    ["apple","orage","pair"]

    >>>appext(["apple","orange"],["blueberry","strawberry","blackberry"])

    ["apple","orange","blueberry","strawberry","blackberry"]
    """

    if type(data) is list:
        origlist.extend(data)
    else:
        origlist.append(data)
    return origlist


def find_from_list(list, key, target_value):
    """Finds the first instance of a specified item/key pair from a list of JSON
    objects, and returns the object.
    """

    for item in list:
        if item[key] == target_value:
            return item


### Async Functions ###


async def collect_files_recursive(path, github_api, oauth_token):

    """Collect the contents of a GitHub repo.
    Returns a list of all files in the repo. Does not work with submodules.
    """
    responses = []
    print("attempting get request with URL '" + path + "'")
    response = await github_api.getitem(
        path,
        accept="application/vnd.github.VERSION.object",
        oauth_token=oauth_token,
    )
    for item in response["entries"]:
        if item["type"] == "file":
            responses.append(item)
        elif item["type"] == "dir":
            recursive_responses = await collect_files_recursive(
                path + item["name"] + "/", github_api, oauth_token
            )
            responses = appext(responses, recursive_responses)
    return responses


class GithubFile:
    def __init__(self, gh_api, token, owner, repo) -> None:
        self.gh_api = gh_api
        self.oath_token = token
        self.owner = owner
        self.repo = repo
        self.url = None
        self.github_object = None
        self.download_url = None
        self.file_data = None
        self.showcase_repo_target = None
        self.included_directories = None


class ShowcaseFile(GithubFile):
    def __init__(self, gh_api, token, owner, repo) -> None:
        GithubFile.__init__(gh_api, token, owner, repo)

        self.url = f"/repos/{owner}/{repo}/contents/.showcase"

    async def initialize(self):
        self.github_object = await self.github_api.getItem(
            self.url, oath_token=self.oath_token
        )
        self.download_url = self.github_object["download_url"]
        _file = urllib.request.urlopen(self.download_url)
        self.file_data = json.loads(_file.read())

        self.is_showcase_repo = self.file_data["isShowcaseRepo"]
        self.showscase_enable = self.file_data["showcaseEnable"]
        if not self.is_showcase_repo:
            self.showcase_repo_target = self.file_data["showcaseRepo"]
            self.included_directories = self.file_data["includedDirectories"]


class Repo:
    def __init__(self, gh_api, token, owner, name, showcase_file) -> None:
        self.gh_api = gh_api
        self.oath_token = token
        self.owner = owner
        self.name = name
        self.showcase_file = showcase_file

        self.url = f"/repos/{self.owner}/{self.name}"

    async def initialize(self):
        self.github_object = await self.gh_api.getitem(
            self.url, oath_token=self.oath_token
        )
        self.default_branch = self.github_object["default_branch"]


class ShowcaseRepo(Repo):
    async def create_branch(self, name):
        self.showcase_update_branch_name = name

        _default_branch_url = f"{self.url}/git/ref/heads/{self.default_branch}"
        _new_branch_url_target = f"{self.url}/git/refs"

        self.default_branch_github_object = await self.gh_api.getitem(
            _default_branch_url, oath_token=self.oath_token
        )
        self.default_branch_sha = self.default_branch_github_object["object"][
            "sha"
        ]

        self.showcase_update_branch_github_object = await self.gh_api.post(
            _new_branch_url_target,
            data={
                "ref": f"refs/heads/{self.showcase_update_branch_name}",
                "sha": self.default_branch_sha,
            },
            oath_token=self.oath_token,
        )

    async def get_all_contents_paths(self):
        _contents_target_url = f"{self.url}/contents/"
        self.contents = await collect_files_recursive(
            _contents_target_url, self.gh_api, oauth_token=self.oauth_token
        )
        paths = []
        for file in self.contents:
            paths.append(file["path"])


class OriginatingRepo(Repo):
    async def get_select_content_paths(self):
        _acceptable_file_paths = self.showcase_file.included_directories
        showcase_repo_paths = []

        for path in _acceptable_file_paths:
            _upper_path = f"/repos/{self.owner}/{self.repo}/contents{path}"

            _subset_repo_contents_response = await collect_files_recursive(
                _upper_path, self.gh_api, oauth_token=self.oath_token
            )

            showcase_repo_paths = appext(
                showcase_repo_paths, _subset_repo_contents_response
            )
        return showcase_repo_paths
