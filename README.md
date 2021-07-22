## `.showcase` file format

it's a json file:
| Key | Data |
| --- | --- |
|`showcaseEnable `| `true` if you actually, you know, want the app to run on this repo. `false` if you want to disable running showcaser on this repo. But in the long term, it's better to just uninstall the app from this repo and remove the `.showcase` file.|
|`"isShowcaseRepo"` | `true` if this is the repo that your stuff will be displayed in. Otherwise `false`.|
|`includedDirectories`| A list e.g. `["/src/","/images/"]` of all the directories you want showcaser to copy. Include a single blank entry if you want to copy the root directory, e.g. `[""]`. *Only if `isShowcaseRepo` is `false`.*|
|`excludedFiles`|Any files you don't want showcaser to copy. Path must be from repo root, and no regex matching (e.g. `*.txt` or anything). Sorry. *Only if `isShowcaseRepo` is `false`.*|

example:


```
{
    "showcaseRepo" : "Test-repo-2",
    "includedDirectories" : [
        "/src"
    ],
    "excludedFiles" : [
        null
    ]
}
```
