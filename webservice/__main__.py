import asyncio
import os
import sys
import traceback
import urllib.request
import json


import aiohttp
from aiohttp import web
import cachetools
from gidgethub import aiohttp as gh_aiohttp
from gidgethub import routing
from gidgethub import sansio
from gidgethub import apps

router = routing.Router()
cache = cachetools.LRUCache(maxsize=500)

routes = web.RouteTableDef()


@routes.get("/", name="home")
async def handle_get(request):
    return web.Response(text="Hello world")


@routes.post("/webhook")
async def webhook(request):
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


@router.register("pull_request", action="closed")
async def PR_closed(event, gh, *args, **kwargs):
    installation_id = event.data["installation"]["id"]
    installation_access_token = await apps.get_installation_access_token(
        gh,
        installation_id=installation_id,
        app_id=os.environ.get("GH_APP_ID"),
        private_key=os.environ.get("GH_PRIVATE_KEY"),
    )
    if(event.data["pull_request"]["merged"]== True):
        print("A Pull request was merged")
        path = ".showcase"
        owner = event.data["repository"]["owner"]["login"]
        repo = event.data["repository"]["name"]

        showcaseFileTargetURL = "/repos/"+owner+"/"+repo+"/contents/"+path
        #print(showcaseFileTargetURL)

        localShowcaseFileResponse = await gh.getitem(showcaseFileTargetURL,oauth_token=installation_access_token["token"])
        #print(response)

        localShowcaseFile = urllib.request.urlopen(localShowcaseFileResponse["download_url"])
        localShowcaseData = json.loads(localShowcaseFile.read())
        #print(localShowcaseData)
        #print(localShowcaseData["isShowcaseRepo"])

        showcaseRepo = localShowcaseData["showcaseRepo"]

        showcaseRepoTargetURL = "/repos/"+owner+"/"+showcaseRepo

        showcaseRepoResponse = await gh.getitem(showcaseRepoTargetURL,oauth_token=installation_access_token["token"])

        showcaseRepoDefaultBranch = showcaseRepoResponse["default_branch"]

        showcaseRepoDefaultBranchTargetURL = showcaseRepoTargetURL+"/git/ref/heads/"+showcaseRepoDefaultBranch

        showcaseRepoDefaultBranchResponse = await gh.getitem(showcaseRepoDefaultBranchTargetURL,oauth_token=installation_access_token["token"])

        showcaseRepoNewBranchTargetURL = f"/repos/{owner}/{showcaseRepo}/git/refs"


        newBranchCreatedresponse = await gh.post(
            showcaseRepoNewBranchTargetURL,
            data={
                "ref": "refs/heads/showcase-update ",
                "sha": showcaseRepoDefaultBranchResponse["sha"]
            },
            oauth_token=installation_access_token["token"]
        )

        print(newBranchCreatedresponse)

    elif(event.data["pull_request"]["merged"]==False):
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
