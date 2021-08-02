### Imports ###
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


### Async GitHub App Setup ###

router = routing.Router()
cache = cachetools.LRUCache(maxsize=500)

routes = web.RouteTableDef()


### Supporting Functions ###

def appext(origlist,data):
    
    '''Short for "append/extend". This takes a list and some single item or 
    iterable. If it's an item, it uses the .append() method to add it to the end
    of the list, and if it's a list, it uses the .extend() method to add it to 
    the end of the list. It then returns the list. 

    >>>appext(["apple","orange"],"pear")

    ["apple","orage","pair"]

    >>>appext(["apple","orange"],["blueberry","strawberry","blackberry"])

    ["apple","orange","blueberry","strawberry","blackberry"]
    '''

    if(type(data) is list):
        origlist.extend(data)
    else:
        origlist.append(data)
    return origlist

def findFromList(list,key,targetValue):

    '''Finds the first instance of a specified item/key pair from a list of JSON 
    objects, and returns the object.
    '''

    for item in list:
        if(item[key] == targetValue):
            return item


### Async Functions ###

async def collectRecursive(path, gh, oauth_token):

    '''Collect the contents of a GitHub repo.
    Returns a list of all files in the repo. Does not work with submodules.
    '''
    responses = []
    print("attempting get request with URL '" + path +"'")
    response = await gh.getitem(path,accept="application/vnd.github.VERSION.object",oauth_token=oauth_token)
    for item in response["entries"]:
        if(item["type"]=="file"):
            responses.append(item)
        elif (item["type"]=="dir"):
            recursiveResponses = await collectRecursive(path+item["name"]+"/", gh, oauth_token)
            responses = appext(responses,recursiveResponses)
    return responses

async def placeFile(fileContents,newPath,oldSHA,gh,oauth_token):

    '''Simple wrapper function to place a file into a showcase repo. No return.
    '''

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

async def mergeBranch(url,base_branch, gh,oauth_token):

    '''Simple wrapper function to merge the showcase-update branch into the
    default branch.
    '''

    await gh.post(url, data = {
        "base" : base_branch,
        "head" : "showcase-update", 
    }, 
    oauth_token = oauth_token)


### Webservice Functions ###

@routes.get("/", name="home")
async def handle_get(request):

    '''Handle any get requests. Returns a link to the public project repo
    '''

    return web.Response(text="I don't imagine this this is what you are looking for. Try https://github.com/Esouder/Showcaser")


@routes.post("/webhook")
async def webhook(request):

    '''Boilerplate webhook handler, from 
    https://github.com/Mariatta/github_app_boilerplate. Supports the main app
    processes below
    '''

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

    '''Create and close a 'thanks' issue in every repo the app is installed in
    '''

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
async def PR_opened(event,gh,*args,**kwargs):

    '''Add a comment when an elegeble pull request is opened with info about what 
    showcaser will do, and on which directories it will showcase it.
    '''

    #TODO - Make this message more clear?

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

    if(localShowcaseData["isShowcaseRepo"] == False and localShowcaseData["showcaseEnable"] == True):
        showcaseRepo = localShowcaseData["showcaseRepo"]
        response = await gh.post(
                event.data["pull_request"]["comments_url"],
                data={
                    "body": f"When you merge this pull request, your changes will be automatically reflected accross your linked showcase repository, {showcaseRepo}",
                },
                oauth_token=installation_access_token["token"],
            )

@router.register("pull_request", action="closed")
async def PR_closed(event, gh, *args, **kwargs):

    '''This function is the main workings of the app: when a pull request is 
    closed and merged, this parses approprate .showcase files, copies changes,
    and merges them into the defualt branch of the showcase repo.
    '''

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

        if(localShowcaseData["isShowcaseRepo"] == False and localShowcaseData["showcaseEnable"] == True):

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
            showcaseRepoContentsResponse =  await collectRecursive(showcaseRepoTargetURL+"/contents/",gh,oauth_token=installation_access_token["token"])
            

            showcaseRepoPaths = []
            for file in showcaseRepoContentsResponse:
                showcaseRepoPaths.append(file["path"])

            repoContentsResponse = []
            acceptableFilePaths = localShowcaseData["includedDirectories"]
            for path in acceptableFilePaths:
                upperPath = "/repos/"+owner+"/"+repo+"/contents"+path
                subsetRepoContentsResponse =  await collectRecursive(upperPath,gh,oauth_token=installation_access_token["token"])
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
