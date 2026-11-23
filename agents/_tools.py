"""
Agent Tools — 出行决策 Agent（高德地图 Web 服务 API）

所有工具都只从环境变量 `AMAP_API_KEY` 读取密钥，任何情况下都不会把 Key
写进返回值、日志或模型上下文中。

工具清单：
    resolve_location            地点 → 经纬度（支持地铁站 / 商场 / 地址）
    search_nearby_malls         经纬度 → 附近商场列表（按距离排序）
    match_brands_in_mall        商场 → 品牌门店匹配情况
    get_travel_distance         两点之间 → 直线 / 驾车距离
    find_malls_with_all_brands  一站式编排：位置 + 品牌清单 → 候选商场排名

设计原则：地点、门店、距离一律以高德返回为准，模型不得自行生成。
"""

from __future__ import annotations

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Annotated, Any

import httpx
from agents import function_tool

AMAP_BASE = "https://restapi.amap.com"
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)

# 购物中心类 POI 分类码：商场 / 购物中心 / 普通商场
MALL_TYPES = "060100|060101|060102"


class AmapError(RuntimeError):
    """高德接口调用失败（含未配置 Key、鉴权失败、配额耗尽等）。"""


# 这些错误与「查不到结果」无关，必须原样抛给模型，不能被当成「没有这家店」
FATAL_INFOCODES = {"10001", "10002", "10003", "10005", "10009", "10044", "10045", "20000", "20001", "20002"}


# ========== 基础请求 ==========
def _api_key() -> str:
    key = (os.getenv("AMAP_API_KEY") or "").strip()
    if not key:
        raise AmapError(
            "未配置 AMAP_API_KEY。请在项目 .env 中填入高德「Web 服务」类型的 Key，"
            "本地调试还需要在 EdgeOne Makers 控制台的部署环境变量中配置同名变量。"
        )
    return key


def _get(path: str, params: dict[str, Any]) -> dict[str, Any]:
    """调用高德 v3 接口，统一错误处理（不打印、不返回 Key）。"""
    query = {**params, "key": _api_key(), "output": "JSON"}
    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            resp = client.get(f"{AMAP_BASE}{path}", params=query)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        raise AmapError(f"网络请求失败：{type(exc).__name__}，请检查网络或稍后重试。") from exc
    except ValueError as exc:
        raise AmapError("高德返回内容无法解析为 JSON。") from exc

    if str(data.get("status")) != "1":
        info = data.get("info") or "未知错误"
        code = str(data.get("infocode") or "-")
        hints = {
            "10001": "Key 不正确或已失效，请到高德控制台确认 Key。",
            "10003": "当日访问量已超限，请次日再试或提升配额。",
            "10009": "Key 类型不匹配：本工具需要「Web 服务」类型的 Key，而不是「Web端(JS API)」。",
            "10044": "今日调用量已达上限。",
            "20003": "请求参数缺失或非法，请检查地点名称。",
        }
        raise AmapError(f"高德接口返回错误：{info}（infocode={code}）。{hints.get(code, '')}".strip()) from None
    return data


def _is_fatal(exc: AmapError) -> bool:
    """鉴权 / 配额 / 参数类错误，重试没有意义，必须直接暴露给模型。"""
    text = str(exc)
    if "未配置 AMAP_API_KEY" in text:
        return True
    m = re.search(r"infocode=(\d+)", text)
    return bool(m and m.group(1) in FATAL_INFOCODES)


def _loc(value: str) -> tuple[float, float] | None:
    """解析 'lng,lat' 字符串。"""
    m = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*", value or "")
    if not m:
        return None
    return float(m.group(1)), float(m.group(2))


def _fmt_loc(lng: float, lat: float) -> str:
    return f"{lng:.6f},{lat:.6f}"


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _poi_summary(poi: dict[str, Any], keep_location: bool = True) -> dict[str, Any]:
    """精简 POI 字段，避免把整包原始数据塞进模型上下文。"""
    out: dict[str, Any] = {
        "name": poi.get("name") or "",
        "address": poi.get("address") if isinstance(poi.get("address"), str) else "",
        "distance_m": int(_num(poi.get("distance")) or 0) or None,
        "type": poi.get("type") or "",
        "district": poi.get("adname") or "",
    }
    if keep_location:
        out["location"] = poi.get("location") or ""
    tel = poi.get("tel")
    if isinstance(tel, str) and tel:
        out["tel"] = tel
    return out


# ========== 定位缓存（同一会话内避免重复计费） ==========
_GEO_CACHE: dict[str, dict[str, Any]] = {}
_CACHE_LIMIT = 200


def _cache_put(key: str, value: dict[str, Any]) -> None:
    if len(_GEO_CACHE) >= _CACHE_LIMIT:
        _GEO_CACHE.clear()
    _GEO_CACHE[key] = value


# ========== 内部实现：定位 ==========
def _geocode(address: str, city: str = "") -> list[dict[str, Any]]:
    params: dict[str, Any] = {"address": address}
    if city:
        params["city"] = city
    data = _get("/v3/geocode/geo", params)
    out = []
    for item in data.get("geocodes") or []:
        loc = _loc(item.get("location") or "")
        if not loc:
            continue
        out.append(
            {
                "name": item.get("formatted_address") or address,
                "address": item.get("formatted_address") or "",
                "lng": loc[0],
                "lat": loc[1],
                "city": item.get("city") if isinstance(item.get("city"), str) else "",
                "district": item.get("district") if isinstance(item.get("district"), str) else "",
                "level": item.get("level") or "",
                "source": "geocode",
            }
        )
    return out


def _poi_text(keywords: str, city: str = "", limit: int = 5) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"keywords": keywords, "offset": limit, "page": 1, "extensions": "base"}
    if city:
        params["city"] = city
        params["citylimit"] = "false"
    data = _get("/v3/place/text", params)
    out = []
    for poi in data.get("pois") or []:
        loc = _loc(poi.get("location") or "")
        if not loc:
            continue
        out.append(
            {
                "name": poi.get("name") or keywords,
                "address": poi.get("address") if isinstance(poi.get("address"), str) else "",
                "lng": loc[0],
                "lat": loc[1],
                "city": poi.get("cityname") or "",
                "district": poi.get("adname") or "",
                "type": poi.get("type") or "",
                "source": "poi_text",
            }
        )
    return out


def _resolve(query: str, city: str = "") -> dict[str, Any]:
    """把「红莲南路地铁站」「XX 商场」「116.3,39.9」解析成一个坐标。"""
    raw = (query or "").strip()
    if not raw:
        raise AmapError("地点为空，请提供地铁站 / 商场 / 地址或经纬度。")

    direct = _loc(raw)
    if direct:
        return {"name": raw, "address": "", "lng": direct[0], "lat": direct[1], "source": "coordinates"}

    cache_key = f"{raw}|{city}"
    if cache_key in _GEO_CACHE:
        return _GEO_CACHE[cache_key]

    candidates: list[dict[str, Any]] = []
    errors: list[AmapError] = []
    # 先按地址解析，失败再按 POI 名称搜（地铁站、商场这类名称 POI 更准）
    for fn in (lambda: _geocode(raw, city), lambda: _poi_text(raw, city)):
        try:
            candidates = fn()
        except AmapError as exc:
            if _is_fatal(exc):
                raise
            errors.append(exc)
            candidates = []
        if candidates:
            break

    if not candidates:
        if errors:
            # 接口/网络异常 ≠ 地点不存在，如实上报，不要伪装成「找不到」
            raise errors[-1]
        raise AmapError(
            f"高德没有找到「{raw}」的位置。请补充城市名，或换一个更完整的地点名称（例如「红莲南路地铁站 北京」）。"
        )

    best = candidates[0]
    result = {
        "name": best["name"],
        "address": best.get("address", ""),
        "lng": best["lng"],
        "lat": best["lat"],
        "city": best.get("city", ""),
        "district": best.get("district", ""),
        "source": best.get("source", ""),
        "candidates": [
            {"name": c["name"], "address": c.get("address", ""), "lng": c["lng"], "lat": c["lat"]}
            for c in candidates[:5]
            if c["name"] != best["name"]
        ],
        "ambiguous": len(candidates) > 1,
    }
    _cache_put(cache_key, result)
    return result


# ========== 内部实现：周边检索 ==========
def _around(
    lng: float,
    lat: float,
    keywords: str,
    radius: int,
    types: str = "",
    limit: int = 20,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "location": _fmt_loc(lng, lat),
        "keywords": keywords,
        "radius": max(1, min(int(radius), 50000)),
        "sortrule": "distance",
        "offset": min(max(limit, 1), 25),
        "page": 1,
        "extensions": "base",
    }
    if types:
        params["types"] = types
    data = _get("/v3/place/around", params)
    return data.get("pois") or []


def _search_malls(lng: float, lat: float, radius: int, keyword: str = "") -> list[dict[str, Any]]:
    """附近商场：先用分类码 + 关键词，命中为空时逐级放宽。"""
    attempts = []
    if keyword:
        attempts.append((keyword, ""))
    attempts.append(("购物中心", MALL_TYPES))
    attempts.append(("商场", MALL_TYPES))
    attempts.append(("购物中心", ""))
    attempts.append(("商场", ""))

    seen: set[str] = set()
    results: list[dict[str, Any]] = []
    errors: list[AmapError] = []
    for kw, types in attempts:
        try:
            pois = _around(lng, lat, kw, radius, types=types, limit=25)
        except AmapError as exc:
            if _is_fatal(exc):
                raise
            errors.append(exc)
            continue
        for poi in pois:
            name = poi.get("name") or ""
            if not name or name in seen:
                continue
            seen.add(name)
            results.append(poi)
        if len(results) >= 8:
            break

    if not results and errors and len(errors) == len(attempts):
        raise errors[-1]

    def _dist(poi: dict[str, Any]) -> float:
        return _num(poi.get("distance")) or 1e12

    results.sort(key=_dist)
    return results


def _brand_hits(lng: float, lat: float, brand: str, radius: int) -> list[dict[str, Any]]:
    try:
        pois = _around(lng, lat, brand, radius, limit=10)
    except AmapError as exc:
        if _is_fatal(exc):
            raise
        # 单次查询失败不影响整体判断，但调用方会通过 found=false 体现
        return []
    hits = []
    for poi in pois:
        name = poi.get("name") or ""
        # 只保留名称里真正含品牌关键字的门店，避免高德的关键词模糊匹配误判
        if brand and brand not in name:
            continue
        hits.append(_poi_summary(poi))
    return hits


# ========== Tool: 定位 ==========
@function_tool
def resolve_location(
    location: Annotated[str, "用户提供的地点，例如「红莲南路地铁站」、商场名称、详细地址，或「116.3,39.9」经纬度"],
    city: Annotated[str, "可选：城市名，用于消歧，例如「北京」"] = "",
) -> str:
    """把用户说的地点（地铁站 / 商场 / 地址）解析成经纬度坐标。

    在需要知道用户当前位置、或需要用坐标去搜索商场时先调用本工具。
    返回 JSON：name/lng/lat/address/city，并附带 candidates 备选地点。
    如果 ambiguous=true，说明有多个同名地点，应让用户确认。
    """
    try:
        return json.dumps({"ok": True, **_resolve(location, city)}, ensure_ascii=False)
    except AmapError as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)


# ========== Tool: 附近商场 ==========
@function_tool
def search_nearby_malls(
    lng: Annotated[float, "起点经度"],
    lat: Annotated[float, "起点纬度"],
    radius_m: Annotated[int, "搜索半径（米），常用 1000~8000"] = 5000,
    keyword: Annotated[str, "可选：商场名称关键词，例如「大悦城」"] = "",
) -> str:
    """搜索指定坐标附近的商场 / 购物中心，结果按距离由近到远排序。

    返回 JSON：center、count、malls[]（name、address、distance_m、location、type）。
    距离单位为米，来自高德，不要自行估算。
    """
    try:
        pois = _search_malls(lng, lat, radius_m, keyword)
        malls = [_poi_summary(p) for p in pois]
        return json.dumps(
            {
                "ok": True,
                "center": {"lng": lng, "lat": lat},
                "radius_m": radius_m,
                "count": len(malls),
                "malls": malls,
            },
            ensure_ascii=False,
        )
    except AmapError as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)


# ========== Tool: 品牌门店匹配 ==========
@function_tool
def match_brands_in_mall(
    mall_name: Annotated[str, "商场名称，仅用于回填结果"],
    mall_lng: Annotated[float, "商场经度"],
    mall_lat: Annotated[float, "商场纬度"],
    brands: Annotated[str, "需要核对的品牌，多个用英文逗号分隔，例如「倍轻松,西厅村屋」"],
    radius_m: Annotated[int, "在商场周围多大范围内找门店（米），建议 300~600"] = 400,
) -> str:
    """核对指定商场内（周边一定范围）是否存在这些品牌的门店。

    返回 JSON：brands[] 每项含 brand、found、stores[]（名称、距离、地址）。
    found=false 表示该商场没有检索到该品牌门店，此时不能声称「有」。
    """
    try:
        brand_list = [b.strip() for b in re.split(r"[,，、;/\s]+", brands or "") if b.strip()]
        if not brand_list:
            raise AmapError("没有提供要核对的品牌。")

        def one(brand: str) -> dict[str, Any]:
            hits = _brand_hits(mall_lng, mall_lat, brand, radius_m)
            return {
                "brand": brand,
                "found": bool(hits),
                "stores": hits[:3],
            }

        with ThreadPoolExecutor(max_workers=min(8, len(brand_list))) as pool:
            results = list(pool.map(one, brand_list))

        return json.dumps(
            {
                "ok": True,
                "mall": mall_name,
                "radius_m": radius_m,
                "all_found": all(r["found"] for r in results),
                "brands": results,
            },
            ensure_ascii=False,
        )
    except AmapError as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)


# ========== Tool: 距离 ==========
@function_tool
def get_travel_distance(
    origin: Annotated[str, "起点：地点名称或「lng,lat」"],
    destination: Annotated[str, "终点：地点名称或「lng,lat」"],
    mode: Annotated[str, "距离类型：straight=直线距离，driving=驾车距离，walking=步行距离"] = "straight",
) -> str:
    """计算两点之间的距离。用户问「哪个更近」时用它，不要凭感觉判断。

    返回 JSON：straight_line_m 直线距离（米）、route_m 与 route_duration_s（按 mode 请求时的路线距离与耗时）。
    """
    try:
        start = _resolve(origin)
        end = _resolve(destination)
        type_map = {"straight": 0, "driving": 1, "walking": 3}
        dtype = type_map.get((mode or "straight").strip().lower(), 0)

        data = _get(
            "/v3/distance",
            {
                "origins": _fmt_loc(start["lng"], start["lat"]),
                "destination": _fmt_loc(end["lng"], end["lat"]),
                "type": dtype,
            },
        )
        rows = data.get("results") or []
        row = rows[0] if rows else {}

        result: dict[str, Any] = {
            "ok": True,
            "origin": {"name": start["name"], "lng": start["lng"], "lat": start["lat"]},
            "destination": {"name": end["name"], "lng": end["lng"], "lat": end["lat"]},
            "mode": mode or "straight",
            "route_m": int(_num(row.get("distance")) or 0) or None,
            "route_duration_s": int(_num(row.get("duration")) or 0) or None,
        }
        if dtype != 0:
            # 顺带给出直线距离，便于模型解释「直线/路线」差别
            try:
                straight = _get(
                    "/v3/distance",
                    {
                        "origins": _fmt_loc(start["lng"], start["lat"]),
                        "destination": _fmt_loc(end["lng"], end["lat"]),
                        "type": 0,
                    },
                )
                srows = straight.get("results") or []
                result["straight_line_m"] = int(_num(srows[0].get("distance")) or 0) or None if srows else None
            except AmapError:
                result["straight_line_m"] = None
        else:
            result["straight_line_m"] = result["route_m"]

        return json.dumps(result, ensure_ascii=False)
    except AmapError as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)


# ========== Tool: 一站式推荐 ==========
@function_tool
def find_malls_with_all_brands(
    location: Annotated[str, "用户当前所在位置，例如「红莲南路地铁站」或「116.32,39.89」"],
    brands: Annotated[str, "用户要求的品牌，多个用英文逗号分隔，例如「倍轻松,西厅村屋」"],
    radius_m: Annotated[int, "商场搜索半径（米），默认 5000"] = 5000,
    city: Annotated[str, "可选：城市名，用于地点消歧"] = "",
    mall_keyword: Annotated[str, "可选：指定商场名称关键词"] = "",
    max_malls: Annotated[int, "最多核对多少个商场，默认 8，越大越慢"] = 8,
) -> str:
    """一站式完成：定位 → 找附近商场 → 逐个核对品牌门店 → 按距离排序返回候选。

    「既要有 A 又要有 B 的最近商场」这类需求优先调用本工具，一次拿到结论，
    不要自己循环调用其它工具。返回 JSON：origin、brands、candidates[]
    （mall、distance_m、matched_brands、missing_brands、qualified、stores），
    以及 best（满足全部品牌且最近的商场，可能是 null）。
    """
    try:
        brand_list = [b.strip() for b in re.split(r"[,，、;/\s]+", brands or "") if b.strip()]
        if not brand_list:
            raise AmapError("没有提供要核对的品牌。")

        origin = _resolve(location, city)
        malls = _search_malls(origin["lng"], origin["lat"], radius_m, mall_keyword)
        malls = malls[: max(1, min(int(max_malls), 12))]
        if not malls:
            return json.dumps(
                {
                    "ok": True,
                    "origin": {"name": origin["name"], "lng": origin["lng"], "lat": origin["lat"]},
                    "brands": brand_list,
                    "radius_m": radius_m,
                    "count": 0,
                    "candidates": [],
                    "best": None,
                    "note": f"起点{radius_m}米范围内没有检索到商场，可以建议用户扩大半径。",
                },
                ensure_ascii=False,
            )

        def check(mall: dict[str, Any]) -> dict[str, Any]:
            loc = _loc(mall.get("location") or "")
            if not loc:
                return {}
            hits = {b: _brand_hits(loc[0], loc[1], b, 400) for b in brand_list}
            matched = [b for b in brand_list if hits[b]]
            missing = [b for b in brand_list if not hits[b]]
            return {
                "mall": mall.get("name") or "",
                "address": mall.get("address") if isinstance(mall.get("address"), str) else "",
                "distance_m": int(_num(mall.get("distance")) or 0) or None,
                "location": mall.get("location") or "",
                "qualified": not missing,
                "matched_brands": matched,
                "missing_brands": missing,
                "stores": {
                    b: [{"name": s["name"], "distance_m": s.get("distance_m")} for s in hits[b][:2]]
                    for b in brand_list
                    if hits[b]
                },
            }

        with ThreadPoolExecutor(max_workers=4) as pool:
            candidates = [c for c in pool.map(check, malls) if c]

        def sort_key(item: dict[str, Any]) -> tuple[int, float]:
            return (0 if item["qualified"] else 1, item.get("distance_m") or 1e12)

        candidates.sort(key=sort_key)
        best = next((c for c in candidates if c["qualified"]), None)

        return json.dumps(
            {
                "ok": True,
                "origin": {
                    "name": origin["name"],
                    "address": origin.get("address", ""),
                    "lng": origin["lng"],
                    "lat": origin["lat"],
                },
                "brands": brand_list,
                "radius_m": radius_m,
                "count": len(candidates),
                "candidates": candidates,
                "best": (
                    {k: best[k] for k in ("mall", "address", "distance_m", "location", "stores")} if best else None
                ),
                "note": None if best else "半径内没有任何一个商场同时拥有全部要求的品牌，需要向用户说明并给出替代方案。",
            },
            ensure_ascii=False,
        )
    except AmapError as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
