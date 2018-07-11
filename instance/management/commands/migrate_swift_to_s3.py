# -*- coding: utf-8 -*-
#
# OpenCraft -- tools to aid developing and hosting free software projects
# Copyright (C) 2015-2018 OpenCraft <contact@opencraft.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
"""
Migrate SWIFT assets to S3.
One-time script.
"""

# Imports #####################################################################

import logging
import re
import subprocess
import time

import swiftclient

from django.core.management.base import BaseCommand
from instance.models.openedx_instance import OpenEdXInstance

LOG = logging.getLogger(__name__)

# Desired destination region for S3 bucket.
# TODO: actually we should store each instance's S3 region as a field, same as we do with SWIFT. It could be autodetected to be the same as the SWIFT region for each instance. Or we can force it to be Paris for all. In any case we must store in each instance, and remove it from here
# S3_REGION = 'eu-west-3'  # Paris. But requires AWS v4 signature:  "The authorization mechanism you have provided is not supported. Please use AWS4-HMAC-SHA256."
# S3_REGION = 'eu-central-1'  # Frankfurt.  But it seems it also requires AWS v4 though it succeeds in creating the bucket anyway. It returns the AWS v4 error first and then another one saying "Your previous request to create the named bucket succeeded and you already own it.". It would require more research
S3_REGION = 'eu-west-1'  # Ireland. Doesn't seem to require AWS v4, and doesn't fail either
# S3_REGION = 'us-east-1'  # N. Virginia


# Classes #####################################################################


class Command(BaseCommand):
    """
    Migrate SWIFT to S3.
    """
    help = (
        'Migrate all servers\' data from SWIFT to S3.'
    )

    def __init__(self, *args, **kwargs):
        super(Command, self).__init__(*args, **kwargs)
        self.options = {}
        self.retried = {}

    def _get_swift_connection(self, instance):
        return swiftclient.Connection(
            user=instance.swift_openstack_user,
            key=instance.swift_openstack_password,
            authurl=instance.swift_openstack_auth_url,
            tenant_name=instance.swift_openstack_tenant,
            auth_version='2',
            os_options={'region_name': instance.swift_openstack_region}
        )

    def _create_rclone_config_s3(self, instance):
        """
        Creates rclone config, for S3.
        """
        rclone_config = "rclone config create ocim-s3 s3 access_key_id '%s' secret_access_key '%s' region '%s'" % (instance.s3_access_key, instance.s3_secret_access_key, S3_REGION)
        # LOG.info("Will run this command: %s", rclone_config)
        subprocess.Popen(rclone_config, shell=True)

    def _create_rclone_config_swift(self, instance):
        """
        Creates rclone config, for SWIFT.
        """
        rclone_config = "rclone config create ocim-swift swift user '%s' key '%s' auth '%s' tenant '%s' auth_version '2' region '%s'" % (
            instance.swift_openstack_user,
            instance.swift_openstack_password,
            instance.swift_openstack_auth_url,
            instance.swift_openstack_tenant,
            instance.swift_openstack_region,
        )

        # LOG.info("Will run this command: %s", rclone_config)
        subprocess.Popen(rclone_config, shell=True)

    def _delete_rclone_configs(self):
        subprocess.Popen("rclone config delete ocim-swift", shell=True)
        subprocess.Popen("rclone config delete ocim-s3", shell=True)

    def _copy_subdirectory(self, key_name, new_name, swift_container, s3_bucket):
        """
        Copy subdirectory using rclone
        """
        LOG.info("%s ---> %s", key_name, new_name)
        assert not new_name.startswith('/')
        assert s3_bucket

        command = "rclone copy -v ocim-swift:%s/%s ocim-s3:%s/%s" % (swift_container, key_name, s3_bucket, new_name)
        LOG.info("Will run this command: %s", command)
        p = subprocess.Popen(command, shell=True)
        (output, err) = p.communicate()
        p_status = p.wait()
        # LOG.info("Command output: ", output)

    def _migrate_swift_to_s3(self, instance):
        """Create IAM user, S3 bucket, move all files from SWIFT to S3, and mark the instance as using S3."""
        # It still doesn't do error handling, so the first times you must review that it's doing the right thing

        # Check sanity
        assert instance.storage_type == 'swift'
        assert instance.swift_container_name

        # You may enable/disable many of these sections while testing or re-running, by changing 0 to 1
        if 0:
            LOG.info("Creating IAM user")
            assert not instance.s3_access_key
            assert not instance.s3_secret_access_key

            # The bucket name must be set before creating the user, to limit the user to that bucket
            # Note that bucket names could be different S3 (e.g. instance.bucket transforms _ to -)
            instance.s3_bucket_name = instance.bucket_name

            # Debug only: use different names each time (otherwise AWS complains with HTTP 409 error)
            # instance.s3_bucket_name = "%s-%i" % (instance.s3_bucket_name, int(time.time()))

            instance.save()

            instance.create_iam_user()
            assert instance.s3_access_key
            assert instance.s3_secret_access_key

        if 0:
            LOG.info("Creating bucket (%s). Waiting some seconds between attempts", instance.s3_bucket_name)
            instance._create_bucket(retry_delay=6, attempts=8, location=S3_REGION)

        LOG.info("Preparing rclone")
        # Doesn't hurt to run it several times (it will overwrite old one)
        self._create_rclone_config_s3(instance)
        self._create_rclone_config_swift(instance)

        swift = self._get_swift_connection(instance)

        LOG.info("Migrating container: %s", instance.swift_container_name)

        # This list includes all root files, directories and files contained in directories
        # E.g. 'a.jpg', 'submissions_attachmentsbadges/', 'submissions_attachmentsbadges/something.jpg',
        # 'submissions_attachmentsbadges/folder/', 'submissions_attachmentsbadges/folder/some.pdf'

        all_files = swift.get_container(instance.swift_container_name)[1]
        # LOG.info("All files: ", all_files)

        # We'll iterate through each root file/directory. rclone already copies the subdirectories inside a dir.
        copied = []

        for item in all_files:
            # Get only directory name
            # e.g. 'submissions_attachmentsbadges/folder/some.pdf' -> 'submissions_attachmentsbadges'
            # or 'file.pdf' -> 'file.pdf' (unchanged)
            # Rclone will copy the contents inside
            base_name = re.sub('/.*', '', item['name'])

            LOG.info("PROGRESS: Name: %s. Directory name: %s. Copied: %s", item['name'], base_name, copied)

            # Avoid copying 'submissions_attachmentsbadges/folder/some.pdf' because it was already copied as part of 'submissions_attachmentsbadges'
            if base_name in copied:
                LOG.info("Skipping %s", base_name)
                continue

            # replace new name if they contain submissions_attachments (there is a bug on swift implementation that
            # makes files be uploaded to the wrong directory)
            # The changes to do are like:
            #   submissions_attachmentsbadges/ ---> submissions_attachments/badges
            #   submissions_attachmentsuser_tasks/ ---> submissions_attachments/user_tasks
            # etc. and in addition there's a special case
            #   submissions_attachmentssubmissions_attachments ---> submissions_attachments
            # This part can be expanded as we find new cases through different servers
            new_name = re.sub(r'^(submissions_attachments)/?', '\g<1>/', base_name)
            if new_name == 'submissions_attachments/submissions_attachments':
                # special case. These files inside the submissions_attachments directory itself
                new_name = 'submissions_attachments'

            self._copy_subdirectory(
                base_name,
                new_name,
                swift_container=instance.swift_container_name,
                s3_bucket=instance.s3_bucket_name
            )

            copied.append(base_name)

        LOG.info("Migrated! Copied: %i items. Full list: %s", len(copied), copied)

        if 1:
            LOG.info("Cleaning rclone configs")
            self._delete_rclone_configs()

        if 1:
            LOG.info("Did everything work? To change this instance to S3 type, press ENTER")
            input()
            instance.storage_type = 's3'
            instance.save()
            # This could be automated if it will save work
            LOG.info("Please spawn a server yourself for instance %i, then test it and activate it", instance.id)

        if 0:
            LOG.info("Debug only! Press ENTER to delete IAM & bucket and clear those settings in the instance, and set it back to SWIFT. Then you can test this migration again and again. Or press C-c to end")
            input()
            LOG.info("Deprovisioning S3...")
            instance.deprovision_s3()
            instance.storage_type = 'swift'
            instance.save()
            LOG.info("We're back to SWIFT")


    def handle(self, *args, **options):
        """
        Finds all instances and migrates them.
        """
        self.options = options

        # instances = OpenEdXInstance.objects.filter(storage_type='swift')

        # You can use this to choose the IDs, and filter in batches
        instances = OpenEdXInstance.objects.filter(id__in=[17, ])

        LOG.info("Will migrate %i instances", instances.count())
        for instance in instances:
            self._migrate_swift_to_s3(instance)
