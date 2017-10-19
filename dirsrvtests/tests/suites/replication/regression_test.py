# --- BEGIN COPYRIGHT BLOCK ---
# Copyright (C) 2017 Red Hat, Inc.
# All rights reserved.
#
# License: GPL (version 3 or any later version).
# See LICENSE for details.
# --- END COPYRIGHT BLOCK ---
#
import pytest
from lib389.idm.user import TEST_USER_PROPERTIES, UserAccounts
from lib389.utils import *
from lib389.topologies import topology_m2 as topo_m2
from lib389._constants import *
from . import get_repl_entries

NEW_SUFFIX_NAME = 'test_repl'
NEW_SUFFIX = 'o={}'.format(NEW_SUFFIX_NAME)
NEW_BACKEND = 'repl_base'

DEBUGGING = os.getenv("DEBUGGING", default=False)
if DEBUGGING:
    logging.getLogger(__name__).setLevel(logging.DEBUG)
else:
    logging.getLogger(__name__).setLevel(logging.INFO)
log = logging.getLogger(__name__)


@pytest.fixture(scope="function")
def test_entry(topo_m2, request):
    """Add test entry using UserAccounts"""

    log.info('Adding a test entry user')
    users = UserAccounts(topo_m2.ms["master1"], DEFAULT_SUFFIX)
    tuser = users.create(properties=TEST_USER_PROPERTIES)

    def fin():
        if users.list():
            log.info('Deleting user-{}'.format(tuser.dn))
            tuser.delete()
        else:
            log.info('There is no user to delete')

    request.addfinalizer(fin)
    return tuser


def test_double_delete(topo_m2, test_entry):
    """Check that double delete of the entry doesn't crash server

    :id: 3496c82d-636a-48c9-973c-2455b12164cc
    :setup: Four masters replication setup, a test entry
    :steps:
        1. Delete the entry on the first master
        2. Delete the entry on the second master
        3. Check that server is alive
    :expectedresults:
        1. Entry should be successfully deleted from first master
        2. Entry should be successfully deleted from second aster
        3. Server should me alive
    """

    test_entry_rdn = test_entry.rdn

    log.info('Deleting entry {} from master1'.format(test_entry.dn))
    topo_m2.ms["master1"].delete_s(test_entry.dn)

    log.info('Deleting entry {} from master2'.format(test_entry.dn))
    try:
        topo_m2.ms["master2"].delete_s(test_entry.dn)
    except ldap.NO_SUCH_OBJECT:
        log.info("Entry {} wasn't found master2. It is expected.".format(test_entry.dn))

    log.info('Make searches to check if server is alive')
    entries = get_repl_entries(topo_m2, test_entry_rdn, ["uid"])
    assert not entries, "Entry deletion {} wasn't replicated successfully".format(test_entry.dn)


def test_password_repl_error(topo_m2, test_entry):
    """Check that error about userpassword replication is properly logged

    :id: 714130ff-e4f0-4633-9def-c1f4b24abfef
    :setup: Four masters replication setup, a test entry
    :steps:
        1. Change userpassword on the first master
        2. Restart the servers to flush the logs
        3. Check the error log for an replication error
    :expectedresults:
        1. Password should be successfully changed
        2. Server should be successfully restarted
        3. There should be no replication errors in the error log
    """

    m1 = topo_m2.ms["master1"]
    m2 = topo_m2.ms["master2"]
    TEST_ENTRY_NEW_PASS = 'new_pass'

    log.info('Clean the error log')
    m2.deleteErrorLogs()

    log.info('Set replication loglevel')
    m2.setLogLevel(LOG_REPLICA)

    log.info('Modifying entry {} - change userpassword on master 1'.format(test_entry.dn))
    try:
        m1.modify_s(test_entry.dn, [(ldap.MOD_REPLACE, 'userpassword', TEST_ENTRY_NEW_PASS)])
    except ldap.LDAPError as e:
        log.error('Failed to modify entry (%s): error (%s)' % (test_entry.dn,
                                                               e.message['desc']))
        raise e

    log.info('Restart the servers to flush the logs')
    for num in range(1, 3):
        topo_m2.ms["master{}".format(num)].restart(timeout=10)

    time.sleep(5)

    try:
        log.info('Check that password works on master 2')
        m2.simple_bind_s(test_entry.dn, TEST_ENTRY_NEW_PASS)
        m2.simple_bind_s(DN_DM, PASSWORD)

        log.info('Check the error log for the error with {}'.format(test_entry.dn))
        assert not m2.ds_error_log.match('.*can.t add a change for {}.*'.format(test_entry.dn))
    finally:
        log.info('Reset bind DN to Directory manager')
        for num in range(1, 3):
            topo_m2.ms["master{}".format(num)].simple_bind_s(DN_DM, PASSWORD)
        log.info('Set the default loglevel')
        m2.setLogLevel(LOG_DEFAULT)


def test_invalid_agmt(topo_m2):
    """Test adding that an invalid agreement is properly rejected and does not crash the server

    :id: 6c3b2a7e-edcd-4327-a003-6bd878ff722b
    :setup: Four masters replication setup
    :steps:
        1. Add invalid agreement (nsds5ReplicaEnabled set to invalid value)
        2. Verify the server is still running
    :expectedresults:
        1. Invalid repl agreement should be rejected
        2. Server should be still running
    """

    m1 = topo_m2.ms["master1"]

    # Add invalid agreement (nsds5ReplicaEnabled set to invalid value)
    AGMT_DN = 'cn=whatever,cn=replica,cn="dc=example,dc=com",cn=mapping tree,cn=config'
    try:
        invalid_props = {RA_ENABLED: 'True',  # Invalid value
                         RA_SCHEDULE: '0001-2359 0123456'}
        m1.agreement.create(suffix=DEFAULT_SUFFIX, host='localhost', port=389, properties=invalid_props)
    except ldap.UNWILLING_TO_PERFORM:
        m1.log.info('Invalid repl agreement correctly rejected')
    except ldap.LDAPError as e:
        m1.log.fatal('Got unexpected error adding invalid agreement: ' + str(e))
        assert False
    else:
        m1.log.fatal('Invalid agreement was incorrectly accepted by the server')
        assert False

    # Verify the server is still running
    try:
        m1.simple_bind_s(DN_DM, PASSWORD)
    except ldap.LDAPError as e:
        m1.log.fatal('Failed to bind: ' + str(e))
        assert False


if __name__ == '__main__':
    # Run isolated
    # -s for DEBUG mode
    CURRENT_FILE = os.path.realpath(__file__)
    pytest.main("-s %s" % CURRENT_FILE)