import asyncio
import datetime
import traceback

import pandas as pd
from config import settings
from cache import AsyncTTL
import akshare as ak
import aakshare as aak
import logging

CACHE_PERIOD_MIN_3 = 180
CACHE_PERIOD_HOUR_2 = 7200
CACHE_PERIOD_DAY_1 = 86400
CACHE_PERIOD_DAY_15 = 86400 * 15


@AsyncTTL(time_to_live=CACHE_PERIOD_MIN_3, maxsize=1)
async def get_index():
    now = datetime.datetime.now()
    logging.info(f"getting index for {now}")
    tmp_index = []
    stock_zh_index_spot_df = await aak.stock_zh_index_spot_sina()
    for code in ["sh000001", "sh000300", "sh000016", "sz399006"]:
        row = stock_zh_index_spot_df[stock_zh_index_spot_df["代码"] == code].iloc[0]
        tmp_index.append(
            {
                "name": row["名称"],
                "code": row["代码"],
                "price": row["最新价"],
                "rate": row["涨跌幅"],
            }
        )

    return now, tmp_index


@AsyncTTL(time_to_live=CACHE_PERIOD_MIN_3, maxsize=1)
async def get_index_new():
    now = datetime.datetime.now()
    logging.info(f"getting index for {now}")
    tmp_index = []

    sh_future = aak.stock_zh_index_spot_em("上证系列指数")
    sz_future = aak.stock_zh_index_spot_em("深证系列指数")
    zz_future = aak.stock_zh_index_spot_em("中证系列指数")

    sh_index, sz_index, zz_index = await asyncio.gather(sh_future, sz_future, zz_future)

    all_index = pd.concat([sh_index, sz_index, zz_index])
    print(all_index, all_index.shape)
    for code in ["000001", "000300", "000016", "399006", "000906"]:
        print(code)
        row = all_index[all_index["代码"] == code].iloc[0]
        tmp_index.append(
            {
                "name": row["名称"],
                "code": row["代码"],
                "price": row["最新价"],
                "rate": row["涨跌幅"],
                "start": row["今开"],
                "high": row["最高"],
                "low": row["最低"],
            }
        )

    return now, tmp_index


@AsyncTTL(time_to_live=CACHE_PERIOD_DAY_15, maxsize=1)
async def get_fund_rate(code: str):
    logging.info(f"getting fund rate for code {code}")
    fund_ratio = await aak.fund_rating_all()
    selected_fund = fund_ratio[fund_ratio.代码 == code]
    selected_fund = selected_fund.iloc[0]

    ret = {}

    for name in ["上海证券", "招商证券", "济安金信"]:
        value = selected_fund[name]
        if not value or pd.isna(value):
            continue
        ret[name] = value

    return ret


@AsyncTTL(time_to_live=CACHE_PERIOD_DAY_15, maxsize=1024)
async def get_fund_hold_stack(code: str):
    logging.info(f"getting fund hold stack for {code}")
    today = datetime.date.today()

    try:
        year = today.year
        fund_portfolio_hold_em_df = await aak.fund_portfolio_hold_em(
            symbol=code, date=f"{year}"
        )
        if len(fund_portfolio_hold_em_df) == 0:
            fund_portfolio_hold_em_df = await aak.fund_portfolio_hold_em(
                symbol=code, date=f"{year-1}"
            )
        if len(fund_portfolio_hold_em_df) == 0:
            return []

        first_item = fund_portfolio_hold_em_df.iloc[0]

        season = first_item["季度"]
        fund_portfolio_hold_em_df = fund_portfolio_hold_em_df[
            fund_portfolio_hold_em_df.季度 == season
        ]

        result = []
        for _, row in fund_portfolio_hold_em_df.iterrows():
            if row["占净值比例"] <= 0 or len(result) >= 50:
                continue
            result.append(
                {
                    "code": row["股票代码"],
                    "name": row["股票名称"],
                    "share": row["占净值比例"],
                    "season": season,
                }
            )
    except Exception as e:
        traceback.print_exc()
        logging.error(f"get fund hold stack error: {e}")
        return []
    return result


@AsyncTTL(time_to_live=CACHE_PERIOD_DAY_15, maxsize=1024)
async def get_fund_hold_bond(code: str):
    logging.info(f"getting fund hold bond for {code}")
    today = datetime.date.today()
    try:
        year = today.year
        fund_portfolio_bond_hold_em = await aak.fund_portfolio_bond_hold_em(
            symbol=code, date=f"{year}"
        )
        if len(fund_portfolio_bond_hold_em) == 0:
            fund_portfolio_bond_hold_em = await aak.fund_portfolio_bond_hold_em(
                symbol=code, date=f"{year-1}"
            )
        if len(fund_portfolio_bond_hold_em) == 0:
            return []

        first_item = fund_portfolio_bond_hold_em.iloc[0]

        season = first_item["季度"]
        fund_portfolio_bond_hold_em = fund_portfolio_bond_hold_em[
            fund_portfolio_bond_hold_em.季度 == season
        ]

        result = []
        for _, row in fund_portfolio_bond_hold_em.iterrows():
            if row["占净值比例"] <= 0 or len(result) >= 50:
                continue
            result.append(
                {
                    "code": row["债券代码"],
                    "name": row["债券名称"],
                    "share": row["占净值比例"],
                    "season": season,
                }
            )
    except Exception as e:
        traceback.print_exc()
        logging.error(f"get fund hold bond error: {e}")
        return []
    return result


@AsyncTTL(time_to_live=CACHE_PERIOD_HOUR_2, maxsize=1024)
async def get_fund_info(code: str):
    logging.info(f"getting fund info for {code}")

    future_basic = aak.fund_individual_basic_info_xq(symbol=code)
    future_rate = get_fund_rate(code)
    future_hold_stock = get_fund_hold_stack(code)
    future_hold_bond = get_fund_hold_bond(code)
    future_share = aak.get_fund_share(code)

    basic_ret, rate_ret, stock_ret, bond_ret, fund_share_ret = await asyncio.gather(
        future_basic, future_rate, future_hold_stock, future_hold_bond, future_share
    )

    basic_ret["基金评级"].update(rate_ret)
    basic_ret["持有股票"] = stock_ret
    basic_ret["持有债券"] = bond_ret

    if (stock_share := fund_share_ret.get("stock_share", None)) is not None:
        basic_ret["持有股票占比"] = stock_share
    elif len(basic_ret["持有股票"]) > 0:
        basic_ret["持有股票占比"] = sum(
            [item["share"] for item in basic_ret["持有股票"]]
        )
    else:
        basic_ret["持有股票占比"] = 0

    if (bond_share := fund_share_ret.get("bond_share", None)) is not None:
        basic_ret["持有债券占比"] = bond_share
    elif len(basic_ret["持有债券"]) > 0:
        basic_ret["持有债券占比"] = sum(
            [item["share"] for item in basic_ret["持有债券"]]
        )
    else:
        basic_ret["持有债券占比"] = 0

    return basic_ret


@AsyncTTL(time_to_live=CACHE_PERIOD_MIN_3, maxsize=10)
async def get_rt_factor():
    now = datetime.datetime.now()
    logging.info(f"getting realtime price at {now}")
    future_a_stock = aak.stock_zh_a_spot_em()
    future_h_stock = aak.stock_hk_spot_em()
    future_m_stock = aak.stock_us_spot_em()
    future_bond_normal_index = aak.bond_new_composite_index_cbond(
        indicator="财富", period="总值"
    )
    future_cb_index = aak.bond_cb_index_jsl()
    future_cb = aak.bond_cov_comparison()

    (
        a_stock_ret,
        h_stock_ret,
        m_stock_ret,
        bond_normal_index_ret,
        bond_cb_index_ret,
        bond_cb_ret,
    ) = await asyncio.gather(
        future_a_stock,
        future_h_stock,
        future_m_stock,
        future_bond_normal_index,
        future_cb_index,
        future_cb,
    )

    a_stocks = {}
    for _, row in a_stock_ret.iterrows():
        if pd.isna(row["涨跌幅"]):
            continue
        a_stocks[row["代码"]] = row["涨跌幅"]

    h_stocks = {}
    for _, row in h_stock_ret.iterrows():
        if pd.isna(row["涨跌幅"]):
            continue
        h_stocks[row["代码"]] = row["涨跌幅"]

    m_stocks = {}
    for _, row in m_stock_ret.iterrows():
        if pd.isna(row["涨跌幅"]):
            continue
        code = row["代码"]
        if "." in code:
            code = code.split(".")[1]
        m_stocks[code] = row["涨跌幅"]

    bond_index = {}
    start_price = bond_normal_index_ret.iloc[-2]["value"]
    end_price = bond_normal_index_ret.iloc[-1]["value"]
    bond_rate = (end_price / start_price - 1) * 100
    bond_index["bond"] = bond_rate

    bond_cb_rate = bond_cb_index_ret.iloc[-1]["increase_val"] / 100
    bond_index["bond_cb"] = bond_cb_rate

    for _, row in bond_cb_ret.iterrows():
        code = row["转债代码"]
        rate = row["转债涨跌幅"]
        name = row["转债名称"]
        if pd.isna(rate):
            continue
        bond_index[code] = rate
        bond_index[name] = rate
    return now, a_stocks, h_stocks, m_stocks, bond_index


@AsyncTTL(time_to_live=CACHE_PERIOD_MIN_3, maxsize=1024)
async def get_rt_evaluation(code: str):
    fund_info_future = get_fund_info(code)
    rt_factor_facture = get_rt_factor()

    fund_info, rt_factor = await asyncio.gather(fund_info_future, rt_factor_facture)
    now, a_stocks, h_stocks, m_stocks, bond_index = rt_factor

    logging.info(f"[{code}] start evaluate rate for {code} time {now}")
    stock_share_all = fund_info["持有股票占比"] / 100
    bond_share_all = fund_info["持有债券占比"] / 100

    detailed_price = {"stock": {}, "bond": {}}

    stock_share_account = 0
    stock_price_total = 0
    for stock in fund_info["持有股票"]:
        try:
            stock_code = stock["code"]
            stock_share = stock["share"] / 100

            if stock_code in a_stocks:
                stock_price = a_stocks[stock_code]
            elif stock_code in h_stocks:
                stock_price = h_stocks[stock_code]
            elif stock_code in m_stocks:
                stock_price = m_stocks[stock_code]
            else:
                continue
            logging.info(
                f"[{code}] update stock rate: {stock_code} {stock_price} {stock_share}"
            )
            detailed_price["stock"][stock_code] = stock_price
            stock_share_account += stock_share
            stock_price_total += stock_share * stock_price
        except Exception:
            traceback.print_exc()
            continue
    logging.info(stock_share_account)
    stock_evaluate_rate = (
        stock_price_total / stock_share_account if stock_share_account > 0 else 0
    )
    detailed_price["stock"]["avg"] = stock_evaluate_rate
    logging.info(f"[{code}] update avg stock rate: {stock_evaluate_rate} %")

    try:
        bond_rate = bond_index["bond"]
        logging.info(f"[{code}] update avg bond rate: {bond_rate}")
        bond_cb_rate = bond_index["bond_cb"]
        logging.info(f"[{code}] update avg bond cb rate: {bond_cb_rate}")
    except Exception as e:
        logging.info(f"[{code}] update avg bond error: {e}")
        bond_rate = 0
        bond_cb_rate = 0

    bond_total = 0
    bond_price_total = 0
    for b in fund_info["持有债券"]:
        try:
            name = b["name"]
            bcode = b["code"]
            share = b["share"] / 100
            if name in bond_index:
                bond_price = bond_index[name]
            elif bcode in bond_index:
                bond_price = bond_index[bcode]
            elif "转" in name:
                bond_price = bond_cb_rate
            else:
                bond_price = bond_rate

            detailed_price["bond"][bcode] = bond_price
            logging.info(f"[{code}] update bond rate: {name} {bond_price} {share}")
            bond_total += share
            bond_price_total += share * bond_price
        except Exception:
            continue

    bond_evaluate_rate = bond_price_total / bond_total if bond_total > 0 else 0
    logging.info(f"[{code}] update avg stock rate: {bond_evaluate_rate}%")
    detailed_price["bond"]["avg"] = bond_evaluate_rate

    evaluate_rate = (
        stock_share_all * stock_evaluate_rate + bond_evaluate_rate * bond_share_all
    )
    logging.info(
        f"[{code}] update evaluated: {evaluate_rate} {stock_evaluate_rate}({stock_share_all}) {bond_evaluate_rate}({bond_share_all})"
    )
    return now, fund_info, evaluate_rate, detailed_price
