import asyncio
import os
import sys
import traceback
import urllib.request
import json
import base64


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


# can you tell I'm more of a C guy?
def appext(origlist,data):
    if(type(data) is list):
        origlist.extend(data)
    else:
        origlist.append(data)
    return origlist 


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


async def collectFiles(path, gh, oauth_token, ref=null):
    #get the contents of the directory  
    responses = []
    #would be best if this actually used the ref
    response = await gh.getitem(path,accept="application/vnd.github.VERSION.object",oauth_token=oauth_token)
    for item in response["entries"]:
        #print(item)
        if(item["type"]=="file"):
            responses.append(item)
        elif (item["type"]=="dir"):
            recursiveResponses = await collectFiles(path+item["path"], gh, oauth_token)
            responses = appext(responses,recursiveResponses)
    return responses

async def placeFile(fileContents,newPath,SHA=None,gh,oauth_token):
    response = await gh.put(
            newPath,
            data={
                "message": "Showcaser Auto Commit: Updating Showcased Files",
                "content": fileContents,
                "branch" : "showcase-update",
                "sha" : SHA
            },
            oauth_token=oauth_token 
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


        owner = event.data["repository"]["owner"]["login"]
        repo = event.data["repository"]["name"]

        showcaseFileTargetURL = "/repos/"+owner+"/"+repo+"/contents/"+".showcase"

        localShowcaseFileResponse = await gh.getitem(showcaseFileTargetURL,oauth_token=installation_access_token["token"])

        localShowcaseFile = urllib.request.urlopen(localShowcaseFileResponse["download_url"])

        localShowcaseData = json.loads(localShowcaseFile.read())

        showcaseRepo = localShowcaseData["showcaseRepo"]

        showcaseRepoTargetURL = "/repos/"+owner+"/"+showcaseRepo

        showcaseRepoResponse = await gh.getitem(showcaseRepoTargetURL,oauth_token=installation_access_token["token"])

        showcaseRepoDefaultBranch = showcaseRepoResponse["default_branch"]

        showcaseRepoDefaultBranchTargetURL = showcaseRepoTargetURL+"/git/ref/heads/"+showcaseRepoDefaultBranch

        showcaseRepoDefaultBranchResponse = await gh.getitem(showcaseRepoDefaultBranchTargetURL,oauth_token=installation_access_token["token"])

        showcaseRepoNewBranchTargetURL = f"/repos/{owner}/{showcaseRepo}/git/refs"


        #newBranchCreatedresponse = await gh.post(
        #    showcaseRepoNewBranchTargetURL,
        #    data={
        #        "ref": "refs/heads/showcase-update",
        #        "sha": showcaseRepoDefaultBranchResponse["object"]["sha"]
        #    },
        #    oauth_token=installation_access_token["token"]
        #)
        
        showcaseFolderURL = f"/repos/{owner}/{showcaseRepo}/contents/"+repo
        existingFiles = await collectFiles(showcaseFolderURL,gh,oauth_token=installation_access_token["token"])
        print (existingFiles)



        repoContentsResponse = []
        acceptableFilePaths = localShowcaseData["includedDirectories"]
        for path in acceptableFilePaths:
            upperPath = "/repos/"+owner+"/"+repo+"/contents"+path
            subsetRepoContentsResponse =  await collectFiles(upperPath,gh,oauth_token=installation_access_token["token"])
            repoContentsResponse=appext(repoContentsResponse,subsetRepoContentsResponse)

                for file in repoContentsResponse:
                    fileContents = urllib.request.urlopen(file["download_url"]).read()
                    encodedFileContents = base64.b64encode(fileContents).decode('utf-8')

                     if(file["path"] not in localShowcaseData["excludedFiles"]||file["name"] not ".showcase"):
                        if(file["path"] in existingFiles["path"]):
                        print("file already exists!")
                    else 
                        print("file does not exist!")
                        #await placeFile(encodedFileContents,showcaseRepoTargetURL+'/contents/'+repo+"/"+file["path"],0,gh,oauth_token=installation_access_token["token"])


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
