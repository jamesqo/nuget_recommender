#!/usr/bin/env python3

import argparse
import logging as log
import numpy as np
import os
import pandas as pd
import traceback as tb

from datetime import datetime
from distutils.version import LooseVersion
from itertools import islice
from requests.exceptions import RequestException

from CsvPackageWriter import CsvPackageWriter
from NugetCatalogClient import NugetCatalogClient
from NugetRecommender import NugetRecommender
from SmartTagger import SmartTagger

INFOS_FILENAME = 'package_infos.csv'
PAGES_LIMIT = 10

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '-d', '--debug',
        help="Print debug information",
        action='store_const', dest='log_level', const=log.DEBUG,
        default=log.WARNING
    )
    parser.add_argument(
        '-r', '--refresh-infos',
        help="Refresh package information",
        action='store_const', dest='refresh_infos', const=True,
        default=False
    )
    return parser.parse_args()

def write_infos_file():
    cli = NugetCatalogClient()
    with CsvPackageWriter(filename=INFOS_FILENAME) as writer:
        writer.write_header()
        for page in islice(cli.load_pages(), PAGES_LIMIT):
            for package in page.packages:
                try:
                    writer.write(package.load())
                except RequestException:
                    log.debug("RequestException raised while loading package %s:\n%s", package.id, tb.format_exc())
                    continue

def read_infos_file():
    df = pd.read_csv(INFOS_FILENAME, dtype={
        'authors': str,
        'created': object,
        'description': str,
        'id': str,
        'is_prerelease': bool,
        'listed': bool,
        'summary': str,
        'tags': str,
        'total_downloads': np.int32,
        'verified': bool,
        'version': str
    }, na_filter=False,
       parse_dates=['created'])

    # Remove entries with the same id, keeping the one with the highest version
    df['id_lower'] = df['id'].apply(str.lower)
    df = df.drop_duplicates(subset='id_lower', keep='last').reset_index(drop=True)
    df.drop('id_lower', axis=1, inplace=True)
    return df

def add_days_alive(df):
    now = datetime.now()
    df['days_alive'] = df['created'].apply(lambda date: max((now - date).days, 1))
    return df

def add_downloads_per_day(df):
    df['downloads_per_day'] = df['total_downloads'] / df['days_alive']
    
    m = df.shape[0]
    for index in range(m):
        if df.loc[index, 'downloads_per_day'] < 0:
            df.loc[index, 'downloads_per_day'] = -1 # total_downloads wasn't available
        elif df.loc[index, 'downloads_per_day'] < 1:
            df.loc[index, 'downloads_per_day'] = 1 # Important so np.log doesn't spazz out later

    return df

def add_etags(df):
    tagger = SmartTagger()
    df = tagger.fit_transform(df)
    return df, tagger

def main():
    args = parse_args()
    log.basicConfig(level=args.log_level)

    if args.refresh_infos or not os.path.isfile(INFOS_FILENAME):
        write_infos_file()
    df = read_infos_file()

    df = add_days_alive(df)
    df = add_downloads_per_day(df)
    df, tagger = add_etags(df)
    
    nr = NugetRecommender(tags_vocab=tagger.tags_vocab_)
    nr.fit(df)
    recs = nr.predict(top_n=5)

    pairs = list(recs.items())
    pairs.sort(key=lambda pair: pair[0].lower())
    print('\n'.join([f"{pair[0]}: {pair[1]}" for pair in pairs]))

if __name__ == '__main__':
    main()
