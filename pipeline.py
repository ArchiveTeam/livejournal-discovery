# encoding=utf8
import datetime
from distutils.version import StrictVersion
import hashlib
import os.path
import shutil
import socket
import sys
import time
import random
import requests
import re

import seesaw
from seesaw.config import NumberConfigValue
from seesaw.externalprocess import ExternalProcess
from seesaw.item import ItemInterpolation, ItemValue
from seesaw.pipeline import Pipeline
from seesaw.project import Project
from seesaw.task import SimpleTask, LimitConcurrent
from seesaw.tracker import GetItemFromTracker, PrepareStatsForTracker, \
    UploadWithTracker, SendDoneToTracker


# check the seesaw version
if StrictVersion(seesaw.__version__) < StrictVersion("0.1.5"):
    raise Exception("This pipeline needs seesaw version 0.1.5 or higher.")


###########################################################################
# The version number of this pipeline definition.
#
# Update this each time you make a non-cosmetic change.
# It will be added to the WARC files and reported to the tracker.

VERSION = "20161215.01"
USER_AGENT = 'ArchiveTeam'
TRACKER_ID = 'livejournaldisco'
TRACKER_HOST = 'tracker.archiveteam.org'
DEFAULT_HEADERS = {'User-Agent': 'ArchiveTeam'}


###########################################################################
# This section defines project-specific tasks.
#
# Simple tasks (tasks that do not need any concurrency) are based on the
# SimpleTask class and have a process(item) method that is called for
# each item.
class CheckIP(SimpleTask):
    def __init__(self):
        SimpleTask.__init__(self, "CheckIP")
        self._counter = 0

    def process(self, item):
        # NEW for 2014! Check if we are behind firewall/proxy

        if self._counter <= 0:
            item.log_output('Checking IP address.')
            ip_set = set()

            ip_set.add(socket.gethostbyname('twitter.com'))
            ip_set.add(socket.gethostbyname('facebook.com'))
            ip_set.add(socket.gethostbyname('youtube.com'))
            ip_set.add(socket.gethostbyname('microsoft.com'))
            ip_set.add(socket.gethostbyname('icanhas.cheezburger.com'))
            ip_set.add(socket.gethostbyname('archiveteam.org'))

            if len(ip_set) != 6:
                item.log_output('Got IP addresses: {0}'.format(ip_set))
                item.log_output(
                    'Are you behind a firewall/proxy? That is a big no-no!')
                raise Exception(
                    'Are you behind a firewall/proxy? That is a big no-no!')

        # Check only occasionally
        if self._counter <= 0:
            self._counter = 10
        else:
            self._counter -= 1


class PrepareDirectories(SimpleTask):
    def __init__(self, warc_prefix):
        SimpleTask.__init__(self, "PrepareDirectories")
        self.warc_prefix = warc_prefix

    def process(self, item):
        item_name = item["item_name"]
        dirname = "/".join((item["data_dir"], item_name))

        if os.path.isdir(dirname):
            shutil.rmtree(dirname)

        os.makedirs(dirname)

        item["item_dir"] = dirname
        item["warc_file_base"] = "%s-%s-%s" % (self.warc_prefix,
                                               item_name.replace(':', '_'),
                                               time.strftime("%Y%m%d-%H%M%S"))

        open("%(item_dir)s/%(warc_file_base)s.txt" % item, "w").close()


class MoveFiles(SimpleTask):
    def __init__(self):
        SimpleTask.__init__(self, "MoveFiles")

    def process(self, item):
        os.rename("%(item_dir)s/%(warc_file_base)s.txt" % item,
                  "%(data_dir)s/%(warc_file_base)s.txt" % item)

        shutil.rmtree("%(item_dir)s" % item)


class CustomProcessArgs(object):
    def realize(self, item):
        item_type, item_value = item['item_name'].split(':', 1)

        if item_type == 'profiles':
            return ['python', 'discover.py', item_value, item_type,
                    "%(item_dir)s/%(warc_file_base)s.txt" % item]
        else:
            raise ValueError('unhandled item type: {0}'.format(item_type))

class FetchError(Exception):
    # Custom error class
    pass

def get_hash(filename):
    with open(filename, 'rb') as in_file:
        return hashlib.sha1(in_file.read()).hexdigest()


CWD = os.getcwd()
PIPELINE_SHA1 = get_hash(os.path.join(CWD, 'pipeline.py'))
SCRIPT_SHA1 = get_hash(os.path.join(CWD, 'discover.py'))


def stats_id_function(item):
    # NEW for 2014! Some accountability hashes and stats.
    d = {
        'pipeline_hash': PIPELINE_SHA1,
        'python_version': sys.version,
        'script_hash': SCRIPT_SHA1,
    }

    return d


###########################################################################
# Initialize the project.
#
# This will be shown in the warrior management panel. The logo should not
# be too big. The deadline is optional.
project = Project(
    title="LiveJournal Discovery",
    project_html="""
        <img class="project-logo" alt="Project logo" src="http://archiveteam.org/images/thumb/9/9a/Livejournal_logo.png/800px-Livejournal_logo.png" height="50px" title=""/>
        <h2>LiveJournal profiles discovery phase.
        <span class="links">
             <a href="http://www.livejournal.com/">Website</a> &middot;
             <a href="http://tracker.archiveteam.org/livejournaldisco/">Leaderboard</a>
             <a href="http://archiveteam.org/index.php?title=LiveJournal">Wiki</a> &middot;
         </span>
        </h2>
        <p>This is the profiles discovery phase</p>
    """
)

pipeline = Pipeline(
    CheckIP(),
    GetItemFromTracker("http://%s/%s" % (TRACKER_HOST, TRACKER_ID), downloader,
        VERSION),
    PrepareDirectories(warc_prefix="livejournaldisco"),
    ExternalProcess('Scraper', CustomProcessArgs(),
        max_tries=2,
        accept_on_exit_code=[0],
        env={
            "item_dir": ItemValue("item_dir")
        }
    ),
    PrepareStatsForTracker(
        defaults={"downloader": downloader, "version": VERSION},
        file_groups={
            "data": [
                ItemInterpolation("%(item_dir)s/%(warc_file_base)s.txt")
            ]
        },
        id_function=stats_id_function,
    ),
    MoveFiles(),
    LimitConcurrent(NumberConfigValue(min=1, max=4, default="1",
        name="shared:rsync_threads", title="Rsync threads",
        description="The maximum number of concurrent uploads."),
        UploadWithTracker(
            "http://%s/%s" % (TRACKER_HOST, TRACKER_ID),
            downloader=downloader,
            version=VERSION,
            files=[
                ItemInterpolation("%(data_dir)s/%(warc_file_base)s.txt")
            ],
            rsync_target_source_path=ItemInterpolation("%(data_dir)s/"),
            rsync_extra_args=[
                "--recursive",
                "--partial",
                "--partial-dir", ".rsync-tmp"
            ]
            ),
    ),
    SendDoneToTracker(
        tracker_url="http://%s/%s" % (TRACKER_HOST, TRACKER_ID),
        stats=ItemValue("stats")
    )
)

