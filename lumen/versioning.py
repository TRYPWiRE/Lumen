"""Tiny semantic-version helpers ("1.2.3", "v1.2", "1.2.3-beta")."""
import re


def parse(v):
    v = str(v or "0").strip().lstrip("vV")
    main, _, pre = v.partition("-")
    nums = [int(n) for n in re.findall(r"\d+", main)[:4]]
    while len(nums) < 3:
        nums.append(0)
    # a pre-release sorts before the final release
    return tuple(nums) + ((0, pre) if pre else (1, ""))


def is_newer(candidate, current):
    return parse(candidate) > parse(current)


def compatible(min_app, app_version):
    return not min_app or parse(app_version) >= parse(min_app)
