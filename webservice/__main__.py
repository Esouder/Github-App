### Imports ###
import asyncio
import base64
import json
import os
import sys
import traceback
import urllib.request

import aiohttp
import cachetools
from aiohttp import web
from gidgethub import aiohttp as gh_aiohttp
from gidgethub import apps, routing, sansio

### Async GitHub App Setup ###

router = routing.Router()
cache = cachetools.LRUCache(maxsize=500)

routes = web.RouteTableDef()

### Supporting Functions ###


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


async def collect_files_recursive(path, gh, oauth_token):

    """Collect the contents of a GitHub repo.
    Returns a list of all files in the repo. Does not work with submodules.
    """
    responses = []
    print("attempting get request with URL '" + path + "'")
    response = await gh.getitem(
        path,
        accept="application/vnd.github.VERSION.object",
        oauth_token=oauth_token,
    )
    for item in response["entries"]:
        if item["type"] == "file":
            responses.append(item)
        elif item["type"] == "dir":
            recursive_responses = await collect_recursive(
                path + item["name"] + "/", gh, oauth_token
            )
            responses = appext(responses, recursive_responses)
    return responses


async def place_file(file_contents, new_path, old_SHA, gh, oauth_token):

    """Simple wrapper function to place a file into a showcase repo. No return."""

    response = await gh.put(
        new_path,
        data={
            "message": "Showcaser Auto Commit: Updating Showcased Files",
            "content": file_contents,
            "sha": old_SHA,
            "branch": "showcase-update",
        },
        oauth_token=oauth_token,
    )


async def merge_branch(url, base_branch, gh, oauth_token):

    """Simple wrapper function to merge the showcase-update branch into the
    default branch.
    """

    await gh.post(
        url,
        data={
            "base": base_branch,
            "head": "showcase-update",
        },
        oauth_token=oauth_token,
    )


### Webservice Functions ###


@routes.get("/", name="home")
async def handle_get(request):

    """Handle any get requests. Returns a link to the public project repo"""

    return web.Response(
        text="I don't imagine this this is what you are looking for. Try https://github.com/Esouder/Showcaser"
    )


@routes.post("/webhook")
async def webhook(request):

    """Boilerplate webhook handler, from
    https://github.com/Mariatta/github_app_boilerplate. Supports the main app
    processes below
    """

    try:
        body = await request.read()
        secret = os.environ.get("GH_SECRET")
        event = sansio.Event.from_http(request.headers, body, secret=secret)
        if event.event == "ping":
            return web.Response(status=200)
        async with aiohttp.ClientSession() as session:
            gh = gh_aiohttp.GitHubAPI(session, "demo", cache=cache)

            await asyncio.sleep(1)
            await router.dispatch(event, gh)
        try:
            print("GH requests remaining:", gh.rate_limit.remaining)
        except AttributeError:
            pass
        return web.Response(status=200)
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        return web.Response(status=500)


@router.register("installation", action="created")
async def repo_installation_added(event, gh, *args, **kwargs):

    """Create and close a 'thanks' issue in every repo the app is installed in"""

    installation_id = event.data["installation"]["id"]
    installation_access_token = await apps.get_installation_access_token(
        gh,
        installation_id=installation_id,
        app_id=os.environ.get("GH_APP_ID"),
        private_key=os.environ.get("GH_PRIVATE_KEY"),
    )
    sender_name = event.data["sender"]["login"]

    for repo in event.data["repositories"]:

        repo_full_name = repo["full_name"]
        response = await gh.post(
            f"/repos/{repo_full_name}/issues",
            data={
                "title": "Thanks for installing me",
                "body": f"You're the best! @{sender_name}",
            },
            oauth_token=installation_access_token["token"],
        )
        issue_url = response["url"]
        await gh.patch(
            issue_url,
            data={"state": "closed"},
            oauth_token=installation_access_token["token"],
        )


@router.register("pull_request", action="opened")
async def pull_request_opened(event, gh, *args, **kwargs):

    """Add a comment when an elegeble pull request is opened with info about what
    showcaser will do, and on which directories it will showcase it.
    """

    # TODO - Make this message more clear?

    installation_id = event.data["installation"]["id"]
    repo = event.data["repository"]["name"]
    installation_access_token = await apps.get_installation_access_token(
        gh,
        installation_id=installation_id,
        app_id=os.environ.get("GH_APP_ID"),
        private_key=os.environ.get("GH_PRIVATE_KEY"),
    )
    owner = event.data["repository"]["owner"]["login"]
    repo = event.data["repository"]["name"]

    showcase_file_target_URL = (
        "/repos/" + owner + "/" + repo + "/contents/" + ".showcase"
    )

    local_showcase_file_response = await gh.getitem(
        showcase_file_target_URL,
        oauth_token=installation_access_token["token"],
    )

    local_showcase_file = urllib.request.urlopen(
        local_showcase_file_response["download_url"]
    )

    local_showcase_data = json.loads(local_showcase_file.read())

    if (
        local_showcase_data["isShowcaseRepo"] == False
        and local_showcase_data["showcaseEnable"] == True
    ):
        showcase_repo = local_showcase_data["showcaseRepo"]
        response = await gh.post(
            event.data["pull_request"]["comments_url"],
            data={
                "body": f"When you merge this pull request, your changes will be automatically reflected accross your linked showcase repository, {showcase_repo}",
            },
            oauth_token=installation_access_token["token"],
        )


@router.register("pull_request", action="closed")
async def pull_request_closed(event, gh, *args, **kwargs):

    """This function is the main workings of the app: when a pull request is
    closed and merged, this parses approprate .showcase files, copies changes,
    and merges them into the defualt branch of the showcase repo.
    """

    installation_id = event.data["installation"]["id"]
    installation_access_token = await apps.get_installation_access_token(
        gh,
        installation_id=installation_id,
        app_id=os.environ.get("GH_APP_ID"),
        private_key=os.environ.get("GH_PRIVATE_KEY"),
    )
    if event.data["pull_request"]["merged"] == True:
        print("A Pull request was merged")

        owner = event.data["repository"]["owner"]["login"]
        repo = event.data["repository"]["name"]

        # parse the .showcase file
        showcase_file_target_URL = (
            "/repos/" + owner + "/" + repo + "/contents/" + ".showcase"
        )

        local_showcase_file_response = await gh.getitem(
            showcase_file_target_URL,
            oauth_token=installation_access_token["token"],
        )

        local_showcase_file = urllib.request.urlopen(
            local_showcase_file_response["download_url"]
        )

        local_showcase_data = json.loads(local_showcase_file.read())

        if (
            local_showcase_data["isShowcaseRepo"] == False
            and local_showcase_data["showcaseEnable"] == True
        ):

            # create a new branch in the showcase repo
            showcase_repo = local_showcase_data["showcaseRepo"]

            showcase_repo_target_URL = "/repos/" + owner + "/" + showcase_repo

            showcase_repo_response = await gh.getitem(
                showcase_repo_target_URL,
                oauth_token=installation_access_token["token"],
            )

            showcase_repo_default_branch = showcase_repo_response[
                "default_branch"
            ]

            showcase_repo_default_branch_target_URL = (
                showcase_repo_target_URL
                + "/git/ref/heads/"
                + showcase_repo_default_branch
            )

            showcase_repo_default_branch_response = await gh.getitem(
                showcase_repo_default_branch_target_URL,
                oauth_token=installation_access_token["token"],
            )

            showcase_repo_new_branch_target_URL = (
                f"/repos/{owner}/{showcase_repo}/git/refs"
            )

            new_branch_created_response = await gh.post(
                showcase_repo_new_branch_target_URL,
                data={
                    "ref": "refs/heads/showcase-update",
                    "sha": showcase_repo_default_branch_response["object"][
                        "sha"
                    ],
                },
                oauth_token=installation_access_token["token"],
            )

            # get contents of showcase repo
            showcase_repo_contents_response = []
            showcase_repo_contents_response = await collect_recursive(
                showcase_repo_target_URL + "/contents/",
                gh,
                oauth_token=installation_access_token["token"],
            )

            showcase_repo_paths = []
            for file in showcase_repo_contents_response:
                showcase_repo_paths.append(file["path"])

            # get contents of originating repo
            repo_contents_response = []
            acceptable_file_paths = local_showcase_data["includedDirectories"]
            for path in acceptable_file_paths:
                upper_path = (
                    "/repos/" + owner + "/" + repo + "/contents" + path
                )
                subset_repo_contents_response = await collect_recursive(
                    upper_path,
                    gh,
                    oauth_token=installation_access_token["token"],
                )
                repo_contents_response = appext(
                    repo_contents_response, subset_repo_contents_response
                )

            base_repo_paths = []
            base_repo_paths_for_comparison = []
            for file in repo_contents_response:
                base_repo_paths.append(repo + "/contents/" + file["path"])
                base_repo_paths_for_comparison.append(
                    repo + "/" + file["path"]
                )

            # copy repo contents from originating repo to showcase repo
            for file in repo_contents_response:
                if (
                    file["path"] not in local_showcase_data["excludedFiles"]
                    and file["name"] != ".showcase"
                ):
                    file_contents = urllib.request.urlopen(
                        file["download_url"]
                    ).read()
                    encoded_file_contents = base64.b64encode(
                        file_contents
                    ).decode("utf-8")
                    if (repo + "/" + file["path"]) in showcase_repo_paths:
                        existing_file = find_from_list(
                            showcase_repo_contents_response,
                            "path",
                            repo + "/" + file["path"],
                        )
                        SHA = existing_file["sha"]
                        await place_file(
                            encoded_file_contents,
                            showcase_repo_target_URL
                            + "/contents/"
                            + repo
                            + "/"
                            + file["path"],
                            SHA,
                            gh,
                            oauth_token=installation_access_token["token"],
                        )
                    else:
                        await place_file(
                            encoded_file_contents,
                            showcase_repo_target_URL
                            + "/contents/"
                            + repo
                            + "/"
                            + file["path"],
                            None,
                            gh,
                            oauth_token=installation_access_token["token"],
                        )

            # delete files in showcase repo that are no longer in the originating repo

            showcaseRepoDirectory = (
                showcase_repo_target_URL + "/contents/" + repo + "/"
            )

            for file in showcase_repo_contents_response:
                if (
                    file["path"] not in base_repo_paths_for_comparison
                ) and file["path"][: len(repo)] == repo:
                    await gh.delete(
                        showcase_repo_target_URL + "/contents/" + file["path"],
                        data={
                            "message": "file removal is automatically reflected from changes to source",
                            "sha": file["sha"],
                            "branch": "showcase-update",
                        },
                        oauth_token=installation_access_token["token"],
                    )
            # merge the branches
            await merge_branch(
                showcase_repo_target_URL + "/merges",
                showcase_repo_default_branch,
                gh,
                oauth_token=installation_access_token["token"],
            )
            # delete the showcase update branch
            await gh.delete(
                showcase_repo_new_branch_target_URL + "/heads/showcase-update",
                oauth_token=installation_access_token["token"],
            )

    # don't do anything if the pull request isn't merged
    elif event.data["pull_request"]["merged"] == False:
        print("A merge was not made")
    else:
        print("code is broken")


if __name__ == "__main__":  # pragma: no cover
    app = web.Application()

    app.router.add_routes(routes)
    port = os.environ.get("PORT")
    if port is not None:
        port = int(port)
    web.run_app(app, port=port)
