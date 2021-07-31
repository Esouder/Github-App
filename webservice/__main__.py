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


async def collectURLs(path, gh, oauth_token):
    #get the contents of the directory
    responses = []
    print("attempting get request with URL '" + path +"'")
    response = await gh.getitem(path,accept="application/vnd.github.VERSION.object",oauth_token=oauth_token)
    for item in response["entries"]:
        #print(item)
        if(item["type"]=="file"):
            responses.append(item)
        elif (item["type"]=="dir"):
            recursiveResponses = await collectURLs(path+item["name"]+"/", gh, oauth_token)
            responses = appext(responses,recursiveResponses)
    return responses

async def placeFile(fileContents,newPath,oldSHA,gh,oauth_token):
    response = await gh.put(
            newPath,
            data={
                "message": "Showcaser Auto Commit: Updating Showcased Files",
                "content": fileContents,
                "sha" : oldSHA,
                "branch" : "showcase-update"
            },
            oauth_token=oauth_token 
        )

def findFromList(list,key,targetValue):
    for item in list:
        print("Checking if '"+item[key]+"' (item[\"key\"]) is equal to '"+targetValue+"' (targetValue")
        if(item[key] == targetValue):
            return item

@router.register("pull_request", action="opened")
async def PR_opened(event,gh,*args,**kwargs):
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

    showcaseFileTargetURL = "/repos/"+owner+"/"+repo+"/contents/"+".showcase"

    localShowcaseFileResponse = await gh.getitem(showcaseFileTargetURL,oauth_token=installation_access_token["token"])

    localShowcaseFile = urllib.request.urlopen(localShowcaseFileResponse["download_url"])

    localShowcaseData = json.loads(localShowcaseFile.read())

    showcaseRepo = localShowcaseData["showcaseRepo"]
    if(localShowcaseData["isShowcaseRepo"] == False):
        response = await gh.post(
                event.data["pull_request"]["comments_url"],
                data={
                    "body": f"When you merge this pull request, your changes will be automatically reflected accross your linked showcase repository, {showcaseRepo}",
                },
                oauth_token=installation_access_token["token"],
            )


async def mergeBranch(url,base_branch, gh,oauth_token):
    await gh.post(url, data = {
        "base" : base_branch,
        "head" : "showcase-update", 
    }, 
    oauth_token = oauth_token)


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

        if(localShowcaseData["isShowcaseRepo"] == False):

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
                    "ref": "refs/heads/showcase-update",
                    "sha": showcaseRepoDefaultBranchResponse["object"]["sha"]       
                },
                oauth_token=installation_access_token["token"]
            )

            showcaseRepoContentsResponse = []
            showcaseRepoContentsResponse =  await collectURLs(showcaseRepoTargetURL+"/contents/",gh,oauth_token=installation_access_token["token"])
            

            showcaseRepoPaths = []
            for file in showcaseRepoContentsResponse:
                showcaseRepoPaths.append(file["path"])

            repoContentsResponse = []
            acceptableFilePaths = localShowcaseData["includedDirectories"]
            for path in acceptableFilePaths:
                upperPath = "/repos/"+owner+"/"+repo+"/contents"+path
                subsetRepoContentsResponse =  await collectURLs(upperPath,gh,oauth_token=installation_access_token["token"])
                repoContentsResponse=appext(repoContentsResponse,subsetRepoContentsResponse)

            baseRepoPaths = []
            baseRepoPathsForComparison = []
            for file in repoContentsResponse:
                baseRepoPaths.append(repo+"/contents/"+file["path"])
                baseRepoPathsForComparison.append(repo+"/"+file["path"])

            for file in repoContentsResponse:
                if(file["path"] not in localShowcaseData["excludedFiles"] and file["name"] != ".showcase"):
                    fileContents = urllib.request.urlopen(file["download_url"]).read()
                    encodedFileContents = base64.b64encode(fileContents).decode('utf-8')
                    if((repo+"/"+file["path"]) in showcaseRepoPaths):
                        existingFile = findFromList(showcaseRepoContentsResponse,"path",repo+"/"+file["path"])
                        SHA = existingFile["sha"]
                        await placeFile(encodedFileContents,showcaseRepoTargetURL+'/contents/'+repo+"/"+file["path"],SHA,gh,oauth_token=installation_access_token["token"])
                    else:
                        await placeFile(encodedFileContents,showcaseRepoTargetURL+'/contents/'+repo+"/"+file["path"],None,gh,oauth_token=installation_access_token["token"])

            showcaseRepoDirectory = showcaseRepoTargetURL+'/contents/'+repo+"/"
            
            for file in showcaseRepoContentsResponse:
                if((file["path"] not in (baseRepoPathsForComparison)) and file["path"][:len(repo)] == repo):
                    await gh.delete(showcaseRepoTargetURL+"/contents/"+file["path"], 
                        data = {
                            "message" : "file removal is automatically reflected from changes to source",
                            "sha" : file["sha"],
                            "branch" : "showcase-update"
                        }, oauth_token=installation_access_token["token"])

            
            await mergeBranch(showcaseRepoTargetURL+"/merges",showcaseRepoDefaultBranch,gh,oauth_token=installation_access_token["token"])
            await gh.delete(showcaseRepoNewBranchTargetURL+"/heads/showcase-update",oauth_token=installation_access_token["token"])



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
