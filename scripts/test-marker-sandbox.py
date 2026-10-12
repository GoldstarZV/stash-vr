"""Exercise HereSphere marker writes against a disposable, synthetic Stash library.

Uses only loopback ports 9977 (Stash) and 19666 (stash-vr). No API keys.
Run seed before starting stash-vr; run exercise, restart stash-vr, then verify.
The sandbox must contain a generated marker-test.mp4, never library media.
"""
import argparse
import copy
import json
from pathlib import Path
import time
import urllib.request

STASH = "http://127.0.0.1:9977/graphql"
VR = "http://127.0.0.1:19666"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def post(url, body):
    assert url == STASH or url.startswith(VR + "/")
    request = urllib.request.Request(url, json.dumps(body).encode(),
                                     {"Content-Type": "application/json"})
    with OPENER.open(request, timeout=15) as response:
        return json.load(response)


def gql(query, variables=None):
    response = post(STASH, {"query": query, "variables": variables or {}})
    assert not response.get("errors"), response
    return response["data"]


def until(check, label):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if check():
            print("PASS:", label, flush=True)
            return
        time.sleep(0.1)
    raise AssertionError("Timed out: " + label)


def scene(sid):
    return gql('query($id:ID!){findScene(id:$id){id title rating100 organized tags{id name} '
               'scene_markers{id title seconds end_seconds primary_tag{id name}}}}',
               {"id": sid})["findScene"]


def document(sid):
    return post(VR + "/heresphere/" + sid, {})


def state(s):
    return {
        "markers": sorted(s["scene_markers"], key=lambda m: int(m["id"])),
        "tags": sorted(t["name"] for t in s["tags"]),
        "rating100": s["rating100"], "organized": s["organized"],
    }


def seed(root):
    scenes = gql('{findScenes(filter:{per_page:-1}){scenes{id}}}')['findScenes']['scenes']
    assert not scenes, "Seed requires an empty sandbox"
    assert (root / "media" / "marker-test.mp4").is_file()
    gql('mutation($input:ScanMetadataInput!){metadataScan(input:$input)}', {"input": {
        "paths": [str(root / "media")], "scanGenerateCovers": True,
        "scanGeneratePreviews": False, "scanGenerateSprites": False,
        "scanGeneratePhashes": False,
    }})
    until(lambda: len(gql('{findScenes{scenes{id}}}')['findScenes']['scenes']) == 1,
          "scan synthetic video")
    sid = gql('{findScenes{scenes{id}}}')['findScenes']['scenes'][0]['id']

    def tag(name, parents=None):
        return gql('mutation($input:TagCreateInput!){tagCreate(input:$input){id}}',
                   {"input": {"name": name, "parent_ids": parents or []}})['tagCreate']['id']

    parent = tag("Category")
    vr = tag("vr", [parent])
    category = tag("#Boy/Girl")
    primary = tag("##marker")
    gql('mutation($input:SceneUpdateInput!){sceneUpdate(input:$input){id}}', {"input": {
        "id": sid, "title": "Synthetic marker regression fixture",
        "tag_ids": [vr, category], "rating100": 80, "organized": True,
    }})
    old = gql('mutation($input:SceneMarkerCreateInput!){sceneMarkerCreate(input:$input){id}}',
              {"input": {"scene_id": sid, "title": "Existing", "seconds": 2,
                         "primary_tag_id": primary}})['sceneMarkerCreate']['id']
    return {"scene_id": sid, "existing_id": old}


def exercise(fixture):
    sid = fixture['scene_id']
    # Index initialization loads the tag hierarchy cache.
    post(VR + "/heresphere/", {})
    tags = document(sid)['tags']
    assert any(t['name'] == '#Category:vr' and t['start'] == -1 for t in tags)
    # Reproduce both marker names supplied by the owner, without rating fields.
    tags += [{"name": "##marker:TESTZ", "start": 12000, "end": 20000},
             {"name": "#MVR", "start": 15000},
             {"name": "#MVR:Zero", "start": 0},
             {"name": "Music:Solo", "start": 18000, "end": 22000}]
    post(VR + '/heresphere/' + sid, {'tags': tags})
    until(lambda: len(scene(sid)['scene_markers']) == 5, 'create hash and ordinary markers')
    until(lambda: len([t for t in document(sid)['tags'] if t.get('rating', 0) > 0]) == 5,
          'reload returns all five persisted markers')
    s = scene(sid)
    assert fixture['existing_id'] in [m['id'] for m in s['scene_markers']]
    assert state(s)['tags'] == ['#Boy/Girl', 'vr']
    testz = next(m for m in s['scene_markers'] if m['title'] == 'TESTZ')
    assert testz['primary_tag']['name'] == '##marker'
    assert (testz['seconds'], testz['end_seconds']) == (12, 20)
    zero = next(m for m in s['scene_markers'] if m['title'] == 'Zero')
    assert zero['seconds'] == 0 and zero['end_seconds'] is None
    print('PASS: original ID, exact tag names, times, point marker, and scene tags preserved')

    # Actual names and ranges visible in issue #94. Try both omitted and zero rating.
    legacy = [
        {"name": "P:37", "start": 0, "end": 903000},
        {"name": "P:38", "start": 0, "end": 3613000},
        {"name": "P:39", "start": 0, "end": 3613000},
        {"name": "O:0", "start": 903000, "end": 1806000},
        {"name": "Org:false", "start": 1806000, "end": 2710000},
        {"name": "movie:movie", "start": 2710000, "end": 3613000},
        {"name": "Performer:Example", "start": 0, "end": 3613000},
    ]
    for include_zero in (False, True):
        tags = document(sid)['tags'] + copy.deepcopy(legacy)
        if include_zero:
            for t in tags:
                t.setdefault('rating', 0)
        # A simultaneous real edit is a completion barrier for the asynchronous save.
        title = 'TESTZ-zero' if include_zero else 'TESTZ-absent'
        for t in tags:
            if t.get('rating') == int(testz['id']):
                t.update(name='##marker:' + title, start=13000)
        post(VR + '/heresphere/' + sid, {'tags': tags})
        until(lambda: any(m['title'] == title for m in scene(sid)['scene_markers']),
              'edit with issue #94 metadata, rating ' + ('zero' if include_zero else 'absent'))
        until(lambda: any(t['name'] == '##marker:' + title for t in document(sid)['tags']),
              'edited marker is returned on reopen')
        s = scene(sid)
        assert len(s['scene_markers']) == 5, s
        assert state(s)['tags'] == ['#Boy/Girl', 'vr']
        assert s['rating100'] == 80 and s['organized']
        assert not any(m['primary_tag']['name'] in ('P', 'O', 'Org', 'movie', 'Performer')
                       for m in s['scene_markers'])
        print('PASS: metadata created no markers; existing markers and scene metadata survived')

    # Explicitly remove one real marker; other IDs must survive.
    tags = [t for t in document(sid)['tags'] if t['name'] != '#MVR']
    post(VR + '/heresphere/' + sid, {'tags': tags})
    until(lambda: len(scene(sid)['scene_markers']) == 4, 'delete only the selected marker')
    until(lambda: len([t for t in document(sid)['tags'] if t.get('rating', 0) > 0]) == 4,
          'deletion survives reopening')
    s = scene(sid)
    assert fixture['existing_id'] in [m['id'] for m in s['scene_markers']]
    fixture['expected'] = state(s)
    return fixture


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['seed', 'exercise', 'verify'])
    parser.add_argument('--sandbox-root', type=Path, required=True)
    args = parser.parse_args()
    root = args.sandbox_root.resolve()
    # Read-only guard before any mutation: require this dedicated database and media root.
    assert root.name == 'sandbox-vr-markers'
    cfg = gql('{configuration{general{databasePath stashes{path}}}}')['configuration']['general']
    assert Path(cfg['databasePath']).resolve() == root / 'stash-go.sqlite', cfg
    assert [Path(s['path']).resolve() for s in cfg['stashes']] == [root / 'media'], cfg
    fixture_path = root / 'fixture.json'
    if args.phase == 'seed':
        fixture = seed(root)
    else:
        fixture = json.loads(fixture_path.read_text())
        if args.phase == 'exercise':
            fixture = exercise(fixture)
        else:
            post(VR + '/heresphere/', {})
            assert state(scene(fixture['scene_id'])) == fixture['expected']
            tags = document(fixture['scene_id'])['tags']
            assert len([t for t in tags if t.get('rating', 0) > 0]) == 4
            assert any(t['name'] == '##marker:TESTZ-zero' for t in tags)
            print('PASS: database and HereSphere document match after process restart')
    fixture_path.write_text(json.dumps(fixture, indent=2))


if __name__ == '__main__':
    main()
