"""Unit tests for import-mailbox-to-gmail."""
import unittest
import os
import shutil
import tempfile
import importlib.util
import sys
import mailbox
import email.message
import logging
from unittest.mock import patch, MagicMock

# Load the module dynamically
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
script_path = os.path.join(parent_dir, "import-mailbox-to-gmail.py")
spec = importlib.util.spec_from_file_location("import_mailbox_to_gmail", script_path)
import_mailbox_to_gmail = importlib.util.module_from_spec(spec)
sys.modules["import_mailbox_to_gmail"] = import_mailbox_to_gmail
spec.loader.exec_module(import_mailbox_to_gmail)

class TestImport(unittest.TestCase):
  """Test case for import logic."""

  def setUp(self):
    logging.disable(logging.CRITICAL)
    self.test_dir = tempfile.mkdtemp()
    self.username = 'testuser@example.com'
    self.user_dir = os.path.join(self.test_dir, self.username)
    os.makedirs(self.user_dir)
    self.mbox_path = os.path.join(self.user_dir, 'test.mbox')
    sample_mbox_path = os.path.join(os.path.dirname(__file__), 'sample.mbox')
    shutil.copyfile(sample_mbox_path, self.mbox_path)


  def tearDown(self):
    logging.disable(logging.NOTSET)
    try:
      shutil.rmtree(self.test_dir)
    except OSError as e:
      print(f"Warning: Failed to clean up {self.test_dir}: {e}")

  @patch('import_mailbox_to_gmail.discovery.build')
  def test_import(self, mock_build):
    """Test the import process."""
    # Mock the service and its methods
    mock_service = MagicMock()
    mock_build.return_value = mock_service

    # Mock the labels().list() call to return no existing labels
    mock_service.users().labels().list().execute.return_value = {'labels': []}

    # Mock the labels().create() call to return a new label
    mock_service.users().labels().create().execute.return_value = {
        'id': 'LABEL_1',
        'name': 'test'
    }

    # Mock the messages().import_() call
    mock_service.users().messages().import_().execute.return_value = {'id': 'MSG_ID'}

    # Set up the arguments for the script
    args = MagicMock()
    args.dir = self.test_dir
    args.from_message = 0
    args.fix_msgid = True
    args.replace_quoted_printable = True
    args.num_retries = 3
    args.log = 'test.log'
    args.httplib2debuglevel = 0

    import_mailbox_to_gmail.ARGS = args

    # Call the function that processes the mbox files
    result = import_mailbox_to_gmail.process_mbox_files(
        self.username, mock_service, [])

    # Assertions
    self.assertEqual(result[3], 2) # 2 messages imported
    self.assertEqual(result[4], 0) # 0 messages failed

    # Check that the label was created
    self.assertEqual(mock_service.users().labels().create.call_count, 2)
    mock_service.users().labels().create.assert_any_call(
        userId=self.username,
        body={'messageListVisibility': 'show', 'name': 'test', 'labelListVisibility': 'labelShow'}
    )

    # Check that the messages were imported
    self.assertEqual(mock_service.users().messages().import_().execute.call_count, 2)

  @patch('import_mailbox_to_gmail.discovery.build')
  def test_import_label_failure(self, mock_build):
    """Test that failed label creation increments the failure counter."""
    # Mock the service and its methods
    mock_service = MagicMock()
    mock_build.return_value = mock_service

    # Mock the labels().list() call to return no existing labels
    mock_service.users().labels().list().execute.return_value = {'labels': []}

    # Mock the labels().create() call to raise an exception
    mock_service.users().labels().create().execute.side_effect = Exception("400 Bad Request")

    # Set up the arguments for the script
    args = MagicMock()
    args.dir = self.test_dir
    args.from_message = 0
    args.fix_msgid = True
    args.replace_quoted_printable = True
    args.num_retries = 1
    args.log = 'test.log'
    args.httplib2debuglevel = 0

    import_mailbox_to_gmail.ARGS = args

    # Call the function that processes the mbox files
    result = import_mailbox_to_gmail.process_mbox_files(
        self.username, mock_service, [])

    # Assertions
    # We expect 1 failed label (the one corresponding to test.mbox)
    self.assertEqual(result[2], 1)  # result[2] is number_of_labels_failed

  @patch('import_mailbox_to_gmail.discovery.build')
  def test_import_message_failure(self, mock_build):
    """Test that failed message import increments the failure counter."""
    mock_service = MagicMock()
    mock_build.return_value = mock_service

    mock_service.users().labels().list().execute.return_value = {'labels': []}
    mock_service.users().labels().create().execute.return_value = {
        'id': 'LABEL_1', 'name': 'test'}

    # Mock import_ to raise exception
    mock_service.users().messages().import_().execute.side_effect = Exception(
        "Import Failed")

    args = MagicMock()
    args.dir = self.test_dir
    args.from_message = 0
    args.fix_msgid = True
    args.replace_quoted_printable = True
    args.num_retries = 1
    args.log = 'test.log'
    args.httplib2debuglevel = 0
    import_mailbox_to_gmail.ARGS = args

    result = import_mailbox_to_gmail.process_mbox_files(
        self.username, mock_service, [])

    # Expect 2 messages failed (sample.mbox has 2 messages)
    self.assertEqual(result[4], 2) # result[4] is number_of_messages_failed
    self.assertEqual(result[3], 0) # result[3] is number_of_messages_imported_without_error

  @patch('import_mailbox_to_gmail.process_user')
  @patch('import_mailbox_to_gmail.setup_logging')
  @patch('os.walk')
  def test_main_user_failure_counter(self, mock_walk, _, mock_process_user):
    """Test that failed user processing increments the user failure counter."""
    mock_process_user.return_value = None # Simulate failure

    # Mock os.walk to return one user
    mock_walk.return_value = iter([
        (self.test_dir, [self.username], []) # root
    ])

    with patch('logging.info') as mock_logging_info:
      # We need to simulate arguments passed to main
      import_mailbox_to_gmail.main(
          ['--dir', self.test_dir, '--json', 'creds.json'])

      # Check for user failure logging
      found = False
      for call in mock_logging_info.call_args_list:
        args, _ = call
        if len(args) > 1 and args[0] == '    %d users failed' and args[1] == 1:
          found = True
          break
      self.assertTrue(found, "Did not find expected logging for user failure count")

  @patch('import_mailbox_to_gmail.discovery.build')
  def test_args_noreplaceqp(self, mock_build):
    """Test --noreplaceqp argument behavior."""
    mock_service = MagicMock()
    mock_build.return_value = mock_service
    mock_service.users().labels().list().execute.return_value = {'labels': []}
    mock_service.users().labels().create().execute.return_value = {
        'id': 'LABEL_1', 'name': 'test'}
    mock_service.users().messages().import_().execute.return_value = {
        'id': 'MSG_ID'}

    # Create a mbox with quoted-printable content type
    mbox_path = os.path.join(self.user_dir, 'qp.mbox')
    mbox = mailbox.mbox(mbox_path)
    msg = email.message.Message()
    msg['Subject'] = 'Test QP'
    msg['Content-Type'] = 'text/quoted-printable'
    msg.set_payload('Test')
    mbox.add(msg)
    mbox.flush()
    mbox.close()

    # Test with replace_quoted_printable=True (default)
    args = MagicMock()
    args.dir = self.test_dir
    args.from_message = 0
    args.fix_msgid = True
    args.replace_quoted_printable = True
    args.num_retries = 1
    args.log = 'test.log'
    args.httplib2debuglevel = 0
    import_mailbox_to_gmail.ARGS = args

    with patch('import_mailbox_to_gmail.import_message') as mock_import_message:
      mock_import_message.return_value = True
      import_mailbox_to_gmail.process_mbox_files(self.username, mock_service, [])

      # Verify call arguments
      # First call, first message (sample.mbox) - we skip it as we are testing qp.mbox
      # Actually process_mbox_files processes all mbox files.
      # We should probably clear user dir first or only have qp.mbox
      # But sample.mbox is there from setUp.

      # Find the call for qp.mbox message
      found_replaced = False
      for call in mock_import_message.call_args_list:
        msg_arg = call[0][2]
        if msg_arg['Subject'] == 'Test QP':
          if 'text/plain' in msg_arg['Content-Type']:
            found_replaced = True
      self.assertTrue(found_replaced, "Should have replaced text/quoted-printable with text/plain")

    # Test with replace_quoted_printable=False
    args.replace_quoted_printable = False

    with patch('import_mailbox_to_gmail.import_message') as mock_import_message:
      mock_import_message.return_value = True
      import_mailbox_to_gmail.process_mbox_files(self.username, mock_service, [])

      found_original = False
      for call in mock_import_message.call_args_list:
        msg_arg = call[0][2]
        if msg_arg['Subject'] == 'Test QP':
          if 'text/quoted-printable' in msg_arg['Content-Type']:
            found_original = True
      self.assertTrue(found_original, "Should NOT have replaced text/quoted-printable")

  @patch('import_mailbox_to_gmail.discovery.build')
  def test_args_no_fix_msgid(self, mock_build):
    """Test --no-fix-msgid argument behavior."""
    mock_service = MagicMock()
    mock_build.return_value = mock_service
    mock_service.users().labels().list().execute.return_value = {'labels': []}
    mock_service.users().labels().create().execute.return_value = {
        'id': 'LABEL_1', 'name': 'test'}
    mock_service.users().messages().import_().execute.return_value = {
        'id': 'MSG_ID'}

    # Create a mbox with missing brackets in Message-ID
    mbox_path = os.path.join(self.user_dir, 'nomsgid.mbox')
    mbox = mailbox.mbox(mbox_path)
    msg = email.message.Message()
    msg['Subject'] = 'Test NoMsgID'
    msg['Message-ID'] = 'no-brackets@example.com'
    msg.set_payload('Test')
    mbox.add(msg)
    mbox.flush()
    mbox.close()

    # Test with fix_msgid=True (default)
    args = MagicMock()
    args.dir = self.test_dir
    args.from_message = 0
    args.fix_msgid = True
    args.replace_quoted_printable = True
    args.num_retries = 1
    args.log = 'test.log'
    args.httplib2debuglevel = 0
    import_mailbox_to_gmail.ARGS = args

    with patch('import_mailbox_to_gmail.import_message') as mock_import_message:
      mock_import_message.return_value = True
      import_mailbox_to_gmail.process_mbox_files(self.username, mock_service, [])

      found_fixed = False
      for call in mock_import_message.call_args_list:
        msg_arg = call[0][2]
        if msg_arg['Subject'] == 'Test NoMsgID':
          if msg_arg['Message-ID'] == '<no-brackets@example.com>':
            found_fixed = True
      self.assertTrue(found_fixed, "Should have fixed Message-ID brackets")

    # Test with fix_msgid=False
    args.fix_msgid = False

    with patch('import_mailbox_to_gmail.import_message') as mock_import_message:
      mock_import_message.return_value = True
      import_mailbox_to_gmail.process_mbox_files(self.username, mock_service, [])

      found_original = False
      for call in mock_import_message.call_args_list:
        msg_arg = call[0][2]
        if msg_arg['Subject'] == 'Test NoMsgID':
          if msg_arg['Message-ID'] == 'no-brackets@example.com':
            found_original = True
      self.assertTrue(found_original, "Should NOT have fixed Message-ID brackets")

  @patch('import_mailbox_to_gmail.discovery.build')
  def test_args_from_message(self, mock_build):
    """Test --from_message argument behavior."""
    mock_service = MagicMock()
    mock_build.return_value = mock_service
    mock_service.users().labels().list().execute.return_value = {'labels': []}
    mock_service.users().labels().create().execute.return_value = {
        'id': 'LABEL_1', 'name': 'test'}
    mock_service.users().messages().import_().execute.return_value = {
        'id': 'MSG_ID'}

    # Use sample.mbox which has 2 messages.
    # Set from_message=1, should import only the second message (index 1)

    args = MagicMock()
    args.dir = self.test_dir
    args.from_message = 1
    args.fix_msgid = True
    args.replace_quoted_printable = True
    args.num_retries = 1
    args.log = 'test.log'
    args.httplib2debuglevel = 0
    import_mailbox_to_gmail.ARGS = args

    with patch('import_mailbox_to_gmail.import_message') as mock_import_message:
      mock_import_message.return_value = True
      import_mailbox_to_gmail.process_mbox_files(self.username, mock_service, [])

      # Should be called once for sample.mbox (2nd message)
      # Note: process_mbox_files loops over all mbox files.
      # Ensure we only have sample.mbox or count correctly.
      # setUp copies sample.mbox to test.mbox.

      count = 0
      for call in mock_import_message.call_args_list:
        # Check if this call is for test.mbox (label 'test')
        # process_mbox_files doesn't pass filename to import_message, but label_id.
        # We can check the message subject if needed.
        msg_arg = call[0][2]
        if msg_arg['Subject'] == 'Test message 2':
          count += 1
        if msg_arg['Subject'] == 'Test message 1':
          self.fail("Should have skipped Test message 1")

      self.assertEqual(count, 1)

  @patch('import_mailbox_to_gmail.process_mbox_files')
  @patch('import_mailbox_to_gmail.discovery.build')
  @patch('import_mailbox_to_gmail.AuthorizedHttp')
  @patch('import_mailbox_to_gmail.get_credentials')
  @patch('import_mailbox_to_gmail.set_user_agent')
  def test_process_user_builds_service_without_cache(
      # pylint: disable=too-many-arguments,too-many-positional-arguments
      self, mock_set_ua, mock_get_creds, mock_authed_http, mock_build,
      mock_process_mbox_files):
    """Test that process_user builds the service with cache_discovery=False."""
    mock_get_creds.return_value = MagicMock()
    mock_set_ua.return_value = MagicMock()
    mock_authed_http.return_value = MagicMock()

    # Mock service to avoid further errors
    mock_service = MagicMock()
    mock_build.return_value = mock_service
    mock_service.users().labels().list().execute.return_value = {'labels': []}

    # Mock process_mbox_files to return success
    mock_process_mbox_files.return_value = (0, 0, 0, 0, 0)

    import_mailbox_to_gmail.process_user(self.username)

    # Verify discovery.build was called with cache_discovery=False
    mock_build.assert_called_with(
        'gmail', 'v1', http=mock_authed_http.return_value,
        cache_discovery=False)

    # Verify process_user now forwards credentials so message imports can
    # run concurrently using per-thread services.
    mock_process_mbox_files.assert_called_once_with(
        self.username, mock_service, [], mock_get_creds.return_value)

  @patch('import_mailbox_to_gmail.discovery.build')
  def test_get_service_for_thread_rebuilds_on_credential_change(
      self, mock_build):
    """A worker thread can be reused across different users' credentials
    (e.g. by the --user_concurrency pool). get_service_for_thread must
    rebuild the service rather than silently returning a previous user's
    cached one - otherwise messages could be imported into the wrong
    mailbox."""
    mock_build.side_effect = lambda *a, **k: MagicMock()
    creds_a = MagicMock(name='creds_a')
    creds_b = MagicMock(name='creds_b')

    service_a1 = import_mailbox_to_gmail.get_service_for_thread(creds_a)
    service_a2 = import_mailbox_to_gmail.get_service_for_thread(creds_a)
    service_b = import_mailbox_to_gmail.get_service_for_thread(creds_b)
    service_a3 = import_mailbox_to_gmail.get_service_for_thread(creds_a)

    self.assertIs(service_a1, service_a2)  # same creds: reuse cached service
    self.assertIsNot(service_a1, service_b)  # different creds: rebuild
    self.assertIsNot(service_b, service_a3)  # switching back: rebuild again
    self.assertEqual(mock_build.call_count, 3)

  @patch('import_mailbox_to_gmail.discovery.build')
  def test_message_concurrency_imports_all_messages(self, mock_build):
    """With credentials and message_concurrency > 1, all messages still
    get imported and counted, just via per-thread services."""
    mock_service = MagicMock()
    mock_build.return_value = mock_service
    mock_service.users().labels().list().execute.return_value = {'labels': []}
    mock_service.users().labels().create().execute.return_value = {
        'id': 'LABEL_1', 'name': 'test'}
    mock_service.users().messages().import_().execute.return_value = {
        'id': 'MSG_ID'}

    # Build an mbox with many messages so the bounded thread pool actually
    # has to refill its in-flight window more than once.
    mbox_path = os.path.join(self.user_dir, 'bulk.mbox')
    mbox = mailbox.mbox(mbox_path)
    num_messages = 20
    for i in range(num_messages):
      msg = email.message.Message()
      msg['Subject'] = f'Bulk message {i}'
      msg.set_payload('Test')
      mbox.add(msg)
    mbox.flush()
    mbox.close()
    # Remove sample.mbox so counts below are only for bulk.mbox.
    os.remove(self.mbox_path)

    args = MagicMock()
    args.dir = self.test_dir
    args.from_message = 0
    args.fix_msgid = True
    args.replace_quoted_printable = True
    args.num_retries = 1
    args.log = 'test.log'
    args.httplib2debuglevel = 0
    args.message_concurrency = 5
    import_mailbox_to_gmail.ARGS = args

    fake_credentials = MagicMock()
    result = import_mailbox_to_gmail.process_mbox_files(
        self.username, mock_service, [], fake_credentials)

    self.assertEqual(result[3], num_messages)  # all imported successfully
    self.assertEqual(result[4], 0)             # none failed

    # discovery.build is called once per worker thread (lazily, on first
    # use), so with 5 workers and only 20 short-lived tasks it should be
    # called more than once but no more than message_concurrency times.
    self.assertGreater(mock_build.call_count, 1)
    self.assertLessEqual(mock_build.call_count, args.message_concurrency)

  @patch('import_mailbox_to_gmail.discovery.build')
  def test_message_concurrency_one_uses_passed_service(self, mock_build):
    """With --message_concurrency 1, messages should use the already-built
    service that was passed in, not build a new per-thread one - this is
    also what keeps a single-message-at-a-time, multi-user run
    (--message_concurrency 1 --user_concurrency N) from being able to hit
    the cross-user cache bug fixed in get_service_for_thread."""
    mock_service = MagicMock()
    mock_service.users().labels().list().execute.return_value = {'labels': []}
    mock_service.users().labels().create().execute.return_value = {
        'id': 'LABEL_1', 'name': 'test'}
    mock_service.users().messages().import_().execute.return_value = {
        'id': 'MSG_ID'}

    args = MagicMock()
    args.dir = self.test_dir
    args.from_message = 0
    args.fix_msgid = True
    args.replace_quoted_printable = True
    args.num_retries = 1
    args.log = 'test.log'
    args.httplib2debuglevel = 0
    args.message_concurrency = 1
    import_mailbox_to_gmail.ARGS = args

    fake_credentials = MagicMock()
    result = import_mailbox_to_gmail.process_mbox_files(
        self.username, mock_service, [], fake_credentials)

    self.assertEqual(result[3], 2)  # sample.mbox has 2 messages
    self.assertEqual(result[4], 0)
    mock_build.assert_not_called()
    self.assertEqual(
        mock_service.users().messages().import_().execute.call_count, 2)

  @patch('import_mailbox_to_gmail.get_service_for_thread')
  @patch('import_mailbox_to_gmail.discovery.build')
  def test_message_concurrency_survives_service_build_failure(
      self, mock_build, mock_get_service):
    """If building a per-thread service fails for one message, that should
    count as one failed message - not raise out of process_mbox_file and
    abort the rest of the user's import."""
    mock_service = MagicMock()
    mock_build.return_value = mock_service
    mock_service.users().labels().list().execute.return_value = {'labels': []}
    mock_service.users().labels().create().execute.return_value = {
        'id': 'LABEL_1', 'name': 'test'}
    mock_service.users().messages().import_().execute.return_value = {
        'id': 'MSG_ID'}
    mock_get_service.side_effect = Exception('transient auth failure')

    args = MagicMock()
    args.dir = self.test_dir
    args.from_message = 0
    args.fix_msgid = True
    args.replace_quoted_printable = True
    args.num_retries = 1
    args.log = 'test.log'
    args.httplib2debuglevel = 0
    args.message_concurrency = 4
    import_mailbox_to_gmail.ARGS = args

    fake_credentials = MagicMock()
    # Should not raise, even though every get_service_for_thread call fails.
    result = import_mailbox_to_gmail.process_mbox_files(
        self.username, mock_service, [], fake_credentials)

    self.assertEqual(result[3], 0)  # none succeeded
    self.assertEqual(result[4], 2)  # both messages counted as failed

  @patch('import_mailbox_to_gmail.discovery.build')
  def test_message_concurrency_respects_from_message(self, mock_build):
    """--from_message should still skip earlier messages when running
    concurrently."""
    mock_service = MagicMock()
    mock_build.return_value = mock_service
    mock_service.users().labels().list().execute.return_value = {'labels': []}
    mock_service.users().labels().create().execute.return_value = {
        'id': 'LABEL_1', 'name': 'test'}
    mock_service.users().messages().import_().execute.return_value = {
        'id': 'MSG_ID'}

    args = MagicMock()
    args.dir = self.test_dir
    args.from_message = 1
    args.fix_msgid = True
    args.replace_quoted_printable = True
    args.num_retries = 1
    args.log = 'test.log'
    args.httplib2debuglevel = 0
    args.message_concurrency = 4
    import_mailbox_to_gmail.ARGS = args

    fake_credentials = MagicMock()
    result = import_mailbox_to_gmail.process_mbox_files(
        self.username, mock_service, [], fake_credentials)

    # sample.mbox has 2 messages; from_message=1 should skip the first.
    self.assertEqual(result[3], 1)
    self.assertEqual(result[4], 0)

  @patch('import_mailbox_to_gmail.process_user')
  @patch('import_mailbox_to_gmail.setup_logging')
  @patch('os.walk')
  def test_main_user_concurrency_processes_all_users(
      self, mock_walk, _, mock_process_user):
    """main() should process every user even when run concurrently, and
    correctly aggregate a mix of successes and failures."""
    usernames = ['user1@example.com', 'user2@example.com',
                 'user3@example.com', 'user4@example.com']

    def fake_process_user(username):
      if username == 'user3@example.com':
        return None  # Simulate one failing user among several.
      return (1, 0, 0, 5, 0)

    mock_process_user.side_effect = fake_process_user
    mock_walk.return_value = iter([(self.test_dir, usernames, [])])

    with patch('logging.info') as mock_logging_info:
      import_mailbox_to_gmail.main([
          '--dir', self.test_dir, '--json', 'creds.json',
          '--user_concurrency', '4'])

      self.assertEqual(mock_process_user.call_count, len(usernames))

      def logged(message, value):
        return any(
            len(call.args) > 1 and call.args[0] == message
            and call.args[1] == value
            for call in mock_logging_info.call_args_list)

      self.assertTrue(logged('    %d users imported with no failures', 3))
      self.assertTrue(logged('    %d users failed', 1))
      self.assertTrue(logged('    %d messages imported successfully', 15))

  @patch('import_mailbox_to_gmail.setup_logging')
  def test_main_rejects_non_positive_concurrency(self, _):
    """--message_concurrency/--user_concurrency below 1 should fail with a
    clear argparse error rather than a raw ValueError from
    ThreadPoolExecutor(max_workers=...)."""
    with self.assertRaises(SystemExit):
      import_mailbox_to_gmail.main([
          '--dir', self.test_dir, '--json', 'creds.json',
          '--message_concurrency', '0'])

    with self.assertRaises(SystemExit):
      import_mailbox_to_gmail.main([
          '--dir', self.test_dir, '--json', 'creds.json',
          '--user_concurrency', '-1'])

if __name__ == '__main__':
  unittest.main()
