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
OpenEdXInstance Storage Mixins - Tests
"""

# Imports #####################################################################
from unittest.mock import patch, call

import boto
import ddt
import yaml
from django.conf import settings
from django.test.utils import override_settings

from instance.models.mixins.storage import get_s3_cors_config, get_master_iam_connection, StorageContainer
from instance.tests.base import TestCase
from instance.tests.models.factories.openedx_appserver import make_test_appserver
from instance.tests.models.factories.openedx_instance import OpenEdXInstanceFactory


# Tests #######################################################################

class OpenEdXStorageMixinTestCase(TestCase):
    """
    Tests for OpenEdXStorageMixin
    """

    def check_s3_vars(self, yaml_vars_string):
        """
        Check the the given yaml string includes the expected Open edX S3-related vars/values
        """
        parsed_vars = yaml.load(yaml_vars_string)
        self.assertEqual(parsed_vars['AWS_ACCESS_KEY_ID'], 'test-s3-access-key')
        self.assertEqual(parsed_vars['AWS_SECRET_ACCESS_KEY'], 'test-s3-secret-access-key')

        self.assertEqual(parsed_vars['EDXAPP_AUTH_EXTRA'], {'AWS_STORAGE_BUCKET_NAME': 'test-s3-bucket-name'})
        self.assertEqual(parsed_vars['EDXAPP_AWS_ACCESS_KEY_ID'], 'test-s3-access-key')
        self.assertEqual(parsed_vars['EDXAPP_AWS_SECRET_ACCESS_KEY'], 'test-s3-secret-access-key')

        self.assertEqual(parsed_vars['XQUEUE_AWS_ACCESS_KEY_ID'], 'test-s3-access-key')
        self.assertEqual(parsed_vars['XQUEUE_AWS_SECRET_ACCESS_KEY'], 'test-s3-secret-access-key')
        self.assertEqual(parsed_vars['XQUEUE_UPLOAD_BUCKET'], 'test-s3-bucket-name')

        self.assertEqual(parsed_vars['COMMON_OBJECT_STORE_LOG_SYNC'], True)
        self.assertEqual(parsed_vars['COMMON_OBJECT_STORE_LOG_SYNC_BUCKET'], 'test-s3-bucket-name')
        self.assertEqual(parsed_vars['AWS_S3_LOGS_ACCESS_KEY_ID'], 'test-s3-access-key')
        self.assertEqual(parsed_vars['AWS_S3_LOGS_SECRET_KEY'], 'test-s3-secret-access-key')

    def test_ansible_s3_settings(self):
        """
        Test that get_storage_settings() includes S3 vars, and that they get passed on to the
        AppServer
        """
        instance = OpenEdXInstanceFactory(
            storage_type='s3',
            s3_access_key='test-s3-access-key',
            s3_secret_access_key='test-s3-secret-access-key',
            s3_bucket_name='test-s3-bucket-name',
        )
        self.check_s3_vars(instance.get_storage_settings())
        appserver = make_test_appserver(instance)
        self.check_s3_vars(appserver.configuration_settings)


def get_s3_settings(instance):
    """
    Return expected s3 settings
    """
    s3_settings = {
        "COMMON_ENABLE_AWS_INTEGRATION": 'true',
        "AWS_ACCESS_KEY_ID": instance.s3_access_key,
        "AWS_SECRET_ACCESS_KEY": instance.s3_secret_access_key,

        "EDXAPP_AWS_LOCATION": instance.swift_container_name,
        "EDXAPP_DEFAULT_FILE_STORAGE": 'storages.backends.s3boto.S3BotoStorage',
        "EDXAPP_AWS_ACCESS_KEY_ID": instance.s3_access_key,
        "EDXAPP_AWS_SECRET_ACCESS_KEY": instance.s3_secret_access_key,
        "EDXAPP_AUTH_EXTRA": '\n  AWS_STORAGE_BUCKET_NAME: test\nEDXAPP_AWS_ACCESS_KEY_ID: test',
        "EDXAPP_AWS_S3_CUSTOM_DOMAIN": "{}.s3.amazonaws.com".format(instance.s3_bucket_name),
        "EDXAPP_IMPORT_EXPORT_BUCKET": instance.s3_bucket_name,
        "EDXAPP_FILE_UPLOAD_BUCKET_NAME": instance.s3_bucket_name,
        "EDXAPP_FILE_UPLOAD_STORAGE_PREFIX": '{}/{}'.format(
            instance.swift_container_name,
            'submissions_attachments'
        ),
        "EDXAPP_GRADE_STORAGE_CLASS": 'storages.backends.s3boto.S3BotoStorage',
        "EDXAPP_GRADE_STORAGE_TYPE": 's3',
        "EDXAPP_GRADE_BUCKET": instance.s3_bucket_name,
        "EDXAPP_GRADE_ROOT_PATH": '{}/{}'.format(instance.swift_container_name, 'grades-download'),
        "EDXAPP_GRADE_STORAGE_KWARGS": (
            '\n  bucket: test\n  location: {}/grades-download'.format(
                instance.swift_container_name
            )
        ),
        "XQUEUE_AWS_ACCESS_KEY_ID": instance.s3_access_key,
        "XQUEUE_AWS_SECRET_ACCESS_KEY": instance.s3_secret_access_key,
        "XQUEUE_UPLOAD_BUCKET": instance.s3_bucket_name,
        "XQUEUE_UPLOAD_PATH_PREFIX": '{}/{}'.format(instance.swift_container_name, 'xqueue'),

        "COMMON_OBJECT_STORE_LOG_SYNC": 'true',
        "COMMON_OBJECT_STORE_LOG_SYNC_BUCKET": instance.s3_bucket_name,
        "COMMON_OBJECT_STORE_LOG_SYNC_PREFIX": '{}/{}'.format(instance.swift_container_name, 'logs/tracking/'),
        "AWS_S3_LOGS": 'true',
        "AWS_S3_LOGS_ACCESS_KEY_ID": instance.s3_access_key,
        "AWS_S3_LOGS_SECRET_KEY": instance.s3_secret_access_key,
    }

    if instance.s3_region:
        s3_settings.update({
            "aws_region": instance.s3_region,
        })

    return s3_settings


def get_swift_settings(instance):
    """
    Return expected Swift settings
    """
    return {
        'EDXAPP_DEFAULT_FILE_STORAGE': 'swift.storage.SwiftStorage',
        'EDXAPP_SWIFT_USERNAME': instance.swift_openstack_user,
        'EDXAPP_SWIFT_KEY': instance.swift_openstack_password,
        'EDXAPP_SWIFT_TENANT_NAME': instance.swift_openstack_tenant,
        'EDXAPP_SWIFT_AUTH_URL': instance.swift_openstack_auth_url,
        'EDXAPP_SWIFT_REGION_NAME': instance.swift_openstack_region,
        'EDXAPP_FILE_UPLOAD_STORAGE_BUCKET_NAME': instance.swift_container_name,

        'XQUEUE_SWIFT_USERNAME': instance.swift_openstack_user,
        'XQUEUE_SWIFT_KEY': instance.swift_openstack_password,
        'XQUEUE_SWIFT_TENANT_NAME': instance.swift_openstack_tenant,
        'XQUEUE_SWIFT_AUTH_URL': instance.swift_openstack_auth_url,
        'XQUEUE_SWIFT_REGION_NAME': instance.swift_openstack_region,
        'XQUEUE_UPLOAD_BUCKET': instance.swift_container_name,

        'SWIFT_LOG_SYNC_USERNAME': instance.swift_openstack_user,
        'SWIFT_LOG_SYNC_PASSWORD': instance.swift_openstack_password,
        'SWIFT_LOG_SYNC_TENANT_NAME': instance.swift_openstack_tenant,
        'SWIFT_LOG_SYNC_AUTH_URL': instance.swift_openstack_auth_url,
        'SWIFT_LOG_SYNC_REGION_NAME': instance.swift_openstack_region,
        'COMMON_OBJECT_STORE_LOG_SYNC_BUCKET': instance.swift_container_name,
    }


# pylint: disable=too-many-public-methods
@ddt.ddt
class SwiftContainerInstanceTestCase(TestCase):
    """
    Tests for Swift container provisioning.
    """

    def check_swift(self, instance, create_swift_container):
        """
        Verify Swift settings on the instance and the number of calls to the Swift API.
        """
        self.assertIs(instance.swift_provisioned, True)
        self.assertEqual(instance.swift_openstack_user, settings.SWIFT_OPENSTACK_USER)
        self.assertEqual(instance.swift_openstack_password, settings.SWIFT_OPENSTACK_PASSWORD)
        self.assertEqual(instance.swift_openstack_tenant, settings.SWIFT_OPENSTACK_TENANT)
        self.assertEqual(instance.swift_openstack_auth_url, settings.SWIFT_OPENSTACK_AUTH_URL)
        self.assertEqual(instance.swift_openstack_region, settings.SWIFT_OPENSTACK_REGION)

        def make_call(container_name):
            """A helper method to prepare mock.call."""
            return call(
                container_name,
                user=instance.swift_openstack_user,
                password=instance.swift_openstack_password,
                tenant=instance.swift_openstack_tenant,
                auth_url=instance.swift_openstack_auth_url,
                region=instance.swift_openstack_region,
            )

        self.assertCountEqual(
            [make_call(container) for container in instance.swift_container_names],
            create_swift_container.call_args_list,
        )

    @patch('instance.openstack_utils.create_swift_container')
    def test_provision_swift(self, create_swift_container):
        """
        Test provisioning Swift containers, and that they are provisioned only once.
        """
        instance = OpenEdXInstanceFactory()
        instance.storage_type = StorageContainer.SWIFT_STORAGE
        instance.provision_swift()
        self.check_swift(instance, create_swift_container)

        # Reset the mock, and provision again.  The container is technically reprovisioned, but this is a no-op.
        create_swift_container.reset_mock()
        instance.provision_swift()
        self.check_swift(instance, create_swift_container)

    @patch('instance.openstack_utils.create_swift_container')
    def test_deprovision_swift(self, create_swift_container):
        """
        Test deprovisioning Swift containers.
        """
        instance = OpenEdXInstanceFactory()
        instance.storage_type = StorageContainer.SWIFT_STORAGE
        instance.provision_swift()
        self.check_swift(instance, create_swift_container)
        instance.deprovision_swift()
        self.assertIs(instance.swift_provisioned, False)

    @patch('instance.openstack_utils.create_swift_container')
    @override_settings(INSTANCE_STORAGE_TYPE=StorageContainer.S3_STORAGE)
    def test_swift_disabled(self, create_swift_container):
        """
        Verify disabling Swift provisioning works.
        """
        instance = OpenEdXInstanceFactory()
        instance.provision_swift()
        self.assertIs(instance.swift_provisioned, False)
        self.assertFalse(create_swift_container.called)

    def check_ansible_settings(self, appserver, expected=True, s3=False):
        """
        Verify the Ansible settings.
        """
        instance = appserver.instance
        if s3:
            expected_settings = get_s3_settings(instance)
        else:
            expected_settings = get_swift_settings(instance)

        # Replace any \' occurrences because some settings may have it while we do a blanket assertion without it.
        # For example: we assert "EDXAPP_SWIFT_TENANT_NAME: 9999999999" is in `ansible_vars`, which would have
        # "EDXAPP_SWIFT_TENANT_NAME: \'9999999999\'", causing a mismatch unless we strip the \'.
        ansible_vars = str(appserver.configuration_settings).replace("\'", '')
        for ansible_var, value in expected_settings.items():
            if expected:
                self.assertRegex(ansible_vars, r'{}:\s*{}'.format(ansible_var, value))
            else:
                self.assertNotRegex(ansible_vars, r'{}:\s*{}'.format(ansible_var, value))

    def test_ansible_settings_swift(self):
        """
        Verify Swift Ansible configuration when Swift is enabled.
        """
        instance = OpenEdXInstanceFactory()
        appserver = make_test_appserver(instance)
        self.check_ansible_settings(appserver)

    @override_settings(INSTANCE_STORAGE_TYPE=StorageContainer.S3_STORAGE)
    def test_ansible_settings_swift_disabled(self):
        """
        Verify Swift Ansible configuration is not included when Swift is disabled.
        """
        instance = OpenEdXInstanceFactory()
        appserver = make_test_appserver(instance)
        self.check_ansible_settings(appserver, expected=False)

    @ddt.data(
        '',
        'eu-west-1',
    )
    def test_ansible_settings_s3(self, s3_region):
        """
        Verify S3 Ansible configuration when S3 is enabled.
        """
        instance = OpenEdXInstanceFactory()
        instance.s3_region = s3_region
        appserver = make_test_appserver(instance, s3=True)
        self.check_ansible_settings(appserver, s3=True)

    @override_settings(
        AWS_ACCESS_KEY='test',
        AWS_SECRET_ACCESS_KEY_ID='test',
        AWS_S3_DEFAULT_HOSTNAME='s3.test.host',
        AWS_S3_CUSTOM_REGION_HOSTNAME='s3.{region}.test.host',
        INSTANCE_STORAGE_TYPE=StorageContainer.S3_STORAGE,
    )
    @ddt.data(
        ('', 's3.test.host'),
        ('region', 's3.region.test.host'),
        ('eu-central-1', 's3.eu-central-1.test.host'),
    )
    @ddt.unpack
    def test_get_s3_connection(self, s3_region, expected_hostname):
        """
        Test get_s3 connection returns right instance
        """
        instance = OpenEdXInstanceFactory()
        instance.s3_region = s3_region
        s3_connection = instance.get_s3_connection()
        self.assertIsInstance(s3_connection, boto.s3.connection.S3Connection)
        self.assertEqual(s3_connection.host, expected_hostname)

    def test_get_s3_policy(self):
        """
        Verify S3 policy is set for correctly
        """
        instance = OpenEdXInstanceFactory()
        policies = [
            (
                '"Action": [\n        "s3:ListBucket",\n        "s3:CreateBucket"'
                ',\n        "s3:DeleteBucket",\n        "s3:PutBucketCORS"\n      ]'
            ),
            '"Resource": [\n        "arn:aws:s3:::{}"\n      ]'.format(instance.s3_bucket_name),
            '"Action": [\n        "s3:*Object*"\n      ]',
            '"Resource": [\n        "arn:aws:s3:::{}/*"\n      ]'.format(instance.s3_bucket_name)
        ]
        policy = instance.get_s3_policy()
        for line in policies:
            self.assertIn(line, policy)

    @patch('boto.s3.connection.S3Connection.create_bucket')
    @patch('boto.s3.bucket.Bucket.set_cors')
    def test_provision_s3(self, set_cors, create_bucket):
        """
        Test s3 provisioning succeeds
        """
        instance = OpenEdXInstanceFactory()
        instance.storage_type = StorageContainer.S3_STORAGE
        instance.s3_access_key = 'test'
        instance.s3_secret_access_key = 'test'
        instance.s3_bucket_name = 'test'
        instance.s3_region = 'test'
        instance.provision_s3()
        create_bucket.assert_called_once_with(instance.s3_bucket_name, location=instance.s3_region)
        self.assertEqual(
            instance.s3_hostname,
            settings.AWS_S3_CUSTOM_REGION_HOSTNAME.format(region=instance.s3_region)
        )

    @patch('boto.s3.connection.S3Connection.create_bucket')
    def test__create_bucket_fails(self, create_bucket):
        """
        Test s3 provisioning fails on bucket creation, and retries up to 4 times
        """
        create_bucket.side_effect = boto.exception.S3ResponseError(403, "Forbidden")
        instance = OpenEdXInstanceFactory()
        instance.s3_access_key = 'test'
        instance.s3_secret_access_key = 'test'
        instance.s3_bucket_name = 'test'
        attempts = 4
        with self.assertRaises(boto.exception.S3ResponseError):
            with self.assertLogs('instance.models.instance', level='INFO') as cm:
                instance._create_bucket(attempts=attempts)
        base_log_text = (
            'INFO:instance.models.instance:instance={} ({!s:.15}) | Retrying bucket creation.'
            ' IAM keys are not propagated yet, attempt %s of {}.'.format(instance.ref.pk, instance.ref.name, attempts)
        )
        self.assertEqual(
            cm.output,
            [base_log_text % i for i in range(1, attempts + 1)]
        )

    @patch('boto.connect_iam')
    @patch('boto.s3.connection.S3Connection')
    def test_deprovision_s3(self, s3_connection, iam_connection):
        """
        Test s3 deprovisioning succeeds
        """
        instance = OpenEdXInstanceFactory()
        instance.storage_type = StorageContainer.S3_STORAGE
        instance.s3_access_key = 'test'
        instance.s3_secret_access_key = 'test'
        instance.s3_bucket_name = 'test'
        instance.s3_region = 'test'
        instance.provision_s3()
        instance.deprovision_s3()
        instance.refresh_from_db()
        self.assertEqual(instance.s3_bucket_name, "")
        self.assertEqual(instance.s3_access_key, "")
        self.assertEqual(instance.s3_secret_access_key, "")
        # We always want to preserve information about a client's preferred region, so s3_region should not be empty.
        self.assertEqual(instance.s3_region, "test")

    @patch('boto.connect_iam')
    @patch('boto.s3.connection.S3Connection')
    def test_deprovision_s3_delete_user_fails(self, s3_connection, connect_iam):
        """
        Test s3 deprovisioning fails on delete_user
        """
        iam_connection = connect_iam()
        iam_connection.delete_access_key.side_effect = boto.exception.BotoServerError(403, "Forbidden")
        instance = OpenEdXInstanceFactory()
        instance.storage_type = StorageContainer.S3_STORAGE
        instance.s3_access_key = 'test'
        instance.s3_secret_access_key = 'test'
        instance.s3_bucket_name = 'test'
        with self.assertLogs("instance.models.instance"):
            instance.deprovision_s3()
        # Since it failed deleting the user, access_keys should not be empty
        self.assertEqual(instance.s3_access_key, "test")
        self.assertEqual(instance.s3_secret_access_key, "test")

    @patch('boto.connect_iam')
    @patch('boto.s3.connection.S3Connection')
    def test_deprovision_s3_delete_bucket_fails(self, s3_connection, connect_iam):
        """
        Test s3 deprovisioning fails on delete_bucket
        """
        s3_connection = s3_connection()
        s3_connection.delete_bucket.side_effect = boto.exception.S3ResponseError(403, "Forbidden")
        instance = OpenEdXInstanceFactory()
        instance.storage_type = StorageContainer.S3_STORAGE
        instance.s3_access_key = 'test'
        instance.s3_secret_access_key = 'test'
        instance.s3_bucket_name = 'test'
        instance.s3_region = 'test'
        with self.assertLogs("instance.models.instance"):
            instance.deprovision_s3()
        instance.refresh_from_db()
        # Since it failed deleting the bucket, s3_bucket_name should not be empty
        self.assertEqual(instance.s3_bucket_name, "test")
        # We always want to preserve information about a client's preferred region, so s3_region should not be empty.
        self.assertEqual(instance.s3_region, "test")
        self.assertEqual(instance.s3_secret_access_key, "")
        self.assertEqual(instance.s3_access_key, "")

    @patch('boto.s3.connection.S3Connection.create_bucket')
    @patch('boto.s3.bucket.Bucket.set_cors')
    @override_settings(AWS_S3_DEFAULT_REGION='test')
    def test_provision_s3_swift(self, set_cors, create_bucket):
        """
        Test s3 provisioning does nothing when SWIFT is enabled
        """
        instance = OpenEdXInstanceFactory()
        instance.storage_type = StorageContainer.SWIFT_STORAGE
        instance.provision_s3()
        instance.refresh_from_db()
        self.assertEqual(instance.s3_bucket_name, '')
        self.assertEqual(instance.s3_access_key, '')
        self.assertEqual(instance.s3_secret_access_key, '')
        self.assertEqual(instance.s3_region, settings.AWS_S3_DEFAULT_REGION)

    @patch('boto.s3.connection.S3Connection.create_bucket')
    @patch('boto.s3.bucket.Bucket.set_cors')
    @override_settings(AWS_S3_DEFAULT_REGION='')
    def test_provision_s3_unconfigured(self, set_cors, create_bucket):
        """
        Test s3 provisioning works with default bucket and IAM
        """
        instance = OpenEdXInstanceFactory()
        instance.storage_type = StorageContainer.S3_STORAGE
        instance.provision_s3()
        create_bucket.assert_called_once_with(
            instance.s3_bucket_name,
            location=settings.AWS_S3_DEFAULT_REGION
        )
        instance.refresh_from_db()
        self.assertIsNotNone(instance.s3_bucket_name)
        self.assertIsNotNone(instance.s3_access_key)
        self.assertIsNotNone(instance.s3_secret_access_key)
        self.assertEqual(instance.s3_region, settings.AWS_S3_DEFAULT_REGION)
        self.assertEqual(instance.s3_hostname, settings.AWS_S3_DEFAULT_HOSTNAME)

    @patch('boto.connect_iam')
    @override_settings(AWS_ACCESS_KEY_ID='test', AWS_SECRET_ACCESS_KEY='test')
    def test_create_iam_user(self, connect_iam):
        """
        Test create_iam_user succeeds and sets the required attributes
        """
        access_keys = {
            'create_access_key_response': {
                'create_access_key_result': {
                    'access_key': {
                        'access_key_id': 'test',
                        'secret_access_key': 'test'
                    }
                }
            }
        }
        connect_iam().create_access_key.return_value = access_keys
        instance = OpenEdXInstanceFactory()
        instance.storage_type = StorageContainer.S3_STORAGE
        instance.create_iam_user()
        instance.refresh_from_db()
        self.assertEqual(instance.s3_access_key, 'test')
        self.assertEqual(instance.s3_secret_access_key, 'test')

    def test_get_s3_cors(self):
        """
        Test get_s3_config succeeds
        """
        s3_cors_config = get_s3_cors_config()
        self.assertEqual(s3_cors_config[0].allowed_method, ['GET', 'PUT'])
        self.assertEqual(s3_cors_config[0].allowed_header, ['*'])
        self.assertEqual(s3_cors_config[0].allowed_origin, ['*'])

    @patch('boto.connect_iam')
    @override_settings(AWS_ACCESS_KEY_ID='test', AWS_SECRET_ACCESS_KEY='test')
    def test_get_master_iam_connection(self, connect_iam):  # pylint: disable=no-self-use
        """
        Test get_s3_config succeeds
        """
        get_master_iam_connection()
        connect_iam.assert_called_once_with('test', 'test')

    def test_bucket_name(self):
        """
        Test bucket_name is correct
        """
        instance = OpenEdXInstanceFactory()
        self.assertRegex(instance.bucket_name, r'ocim-instance[A-Za-z0-9]*-test-example-com')

    def test_iam_username(self):
        """
        Test bucket_name is correct
        """
        instance = OpenEdXInstanceFactory()
        self.assertRegex(instance.iam_username, r'ocim-instance[A-Za-z0-9]*_test_example_com')

    def test_s3_region_default_value(self):
        """
        Test the default value for the S3 region
        """
        instance = OpenEdXInstanceFactory()
        self.assertEqual(instance.s3_region, settings.AWS_S3_DEFAULT_REGION)
