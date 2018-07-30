import json
from unittest.mock import Mock, patch

import responses

from django.core import mail
from django.test import TestCase, override_settings
from django.contrib.messages import get_messages

from opentech.apply.utils.testing import make_request
from opentech.apply.funds.tests.factories import ApplicationSubmissionFactory
from opentech.apply.users.tests.factories import UserFactory, ReviewerFactory

from ..models import Activity, Event
from ..messaging import (
    AdapterBase,
    ActivityAdapter,
    EmailAdapter,
    MessengerBackend,
    MESSAGES,
    SlackAdapter,
)
from .factories import CommentFactory, EventFactory


class TestAdapter(AdapterBase):
    """A test class which will pass the message type to send_message"""
    adapter_type = 'Test Adapter'
    messages = {
        enum: enum.value
        for enum in MESSAGES.__members__.values()
    }

    def send_message(self, message, **kwargs):
        pass

    def recipients(self, message_type, **kwargs):
        return [message_type]

    def log_message(self, message, recipient, event, status):
        pass


class AdapterMixin:
    adapter = None

    def process_kwargs(self, **kwargs):
        if 'user' not in kwargs:
            kwargs['user'] = UserFactory()
        if 'submission' not in kwargs:
            kwargs['submission'] = ApplicationSubmissionFactory()
        if 'request' not in kwargs:
            kwargs['request'] = None

        return kwargs

    def adapter_process(self, message_type, **kwargs):
        kwargs = self.process_kwargs(**kwargs)
        self.adapter.process(message_type, event=EventFactory(submission=kwargs['submission']), **kwargs)


@override_settings(SEND_MESSAGES=True)
class TestBaseAdapter(AdapterMixin, TestCase):
    def setUp(self):
        patched_class = patch.object(TestAdapter, 'send_message')
        self.mock_adapter = patched_class.start()
        self.adapter = TestAdapter()
        self.addCleanup(patched_class.stop)

    def test_can_send_a_message(self):
        message_type = MESSAGES.UPDATE_LEAD
        self.adapter_process(message_type)

        self.adapter.send_message.assert_called_once()
        self.assertEqual(self.adapter.send_message.call_args[0], (message_type.value,))

    def test_doesnt_send_a_message_if_not_configured(self):
        self.adapter_process('this_is_not_a_message_type')

        self.adapter.send_message.assert_not_called()

    def test_calls_method_if_avaliable(self):
        method_name = 'new_method'
        return_message = 'Returned message'
        setattr(self.adapter, method_name, lambda **kw: return_message)
        self.adapter.messages[method_name] = method_name

        self.adapter_process(method_name)

        self.adapter.send_message.assert_called_once()
        self.assertEqual(self.adapter.send_message.call_args[0], (return_message,))

    def test_that_kwargs_passed_to_send_message(self):
        message_type = MESSAGES.UPDATE_LEAD
        kwargs = {'test': 'that', 'these': 'exist'}
        self.adapter_process(message_type, **kwargs)

        self.adapter.send_message.assert_called_once()
        for key in kwargs:
            self.assertTrue(key in self.adapter.send_message.call_args[1])

    def test_that_message_is_formatted(self):
        message_type = MESSAGES.UPDATE_LEAD
        message = 'message value'

        with patch.dict(self.adapter.messages, {message_type: '{message_to_format}'}):
            self.adapter_process(message_type, message_to_format=message)

        self.adapter.send_message.assert_called_once()
        self.assertEqual(self.adapter.send_message.call_args[0], (message,))

    def test_can_include_extra_kwargs(self):
        message_type = MESSAGES.UPDATE_LEAD

        with patch.dict(self.adapter.messages, {message_type: '{extra}'}):
            with patch.object(self.adapter, 'extra_kwargs', return_value={'extra': 'extra'}):
                self.adapter_process(message_type)

        self.adapter.send_message.assert_called_once()
        self.assertTrue('extra' in self.adapter.send_message.call_args[1])

    @override_settings(SEND_MESSAGES=False)
    def test_django_messages_used(self):
        request = make_request()

        self.adapter_process(MESSAGES.UPDATE_LEAD, request=request)

        messages = list(get_messages(request))
        self.assertEqual(len(messages), 1)
        self.assertTrue(MESSAGES.UPDATE_LEAD.value in messages[0].message)
        self.assertTrue(self.adapter.adapter_type in messages[0].message)


class TestMessageBackend(TestCase):
    def setUp(self):
        self.mocked_adapter = Mock(AdapterBase)
        self.backend = MessengerBackend
        self.kwargs = {
            'request': None,
            'user': UserFactory(),
            'submission': ApplicationSubmissionFactory(),
        }

    def test_message_sent_to_adapter(self):
        adapter = self.mocked_adapter()
        messenger = self.backend(adapter)

        messenger(MESSAGES.UPDATE_LEAD, **self.kwargs)

        adapter.process.assert_called_once_with(MESSAGES.UPDATE_LEAD, Event.objects.first(), **self.kwargs)

    def test_message_sent_to_all_adapter(self):
        adapters = [self.mocked_adapter(), self.mocked_adapter()]
        messenger = self.backend(*adapters)

        messenger(MESSAGES.UPDATE_LEAD, **self.kwargs)

        adapter = adapters[0]
        self.assertEqual(adapter.process.call_count, len(adapters))

    def test_event_created(self):
        adapters = [self.mocked_adapter(), self.mocked_adapter()]
        messenger = self.backend(*adapters)
        user = UserFactory()
        self.kwargs.update(user=user)

        messenger(MESSAGES.UPDATE_LEAD, **self.kwargs)

        self.assertEqual(Event.objects.count(), 1)
        self.assertEqual(Event.objects.first().type, MESSAGES.UPDATE_LEAD.name)
        self.assertEqual(Event.objects.first().get_type_display(), MESSAGES.UPDATE_LEAD.value)
        self.assertEqual(Event.objects.first().by, user)


@override_settings(SEND_MESSAGES=True)
class TestActivityAdapter(TestCase):
    def setUp(self):
        self.adapter = ActivityAdapter()

    def test_activity_created(self):
        message = 'test message'
        user = UserFactory()
        submission = ApplicationSubmissionFactory()

        self.adapter.send_message(message, user=user, submission=submission)

        self.assertEqual(Activity.objects.count(), 1)
        activity = Activity.objects.first()
        self.assertEqual(activity.user, user)
        self.assertEqual(activity.message, message)
        self.assertEqual(activity.submission, submission)

    def test_reviewers_message_no_removed(self):
        message = self.adapter.reviewers_updated([1], [])

        self.assertTrue('Added' in message)
        self.assertFalse('Removed' in message)
        self.assertTrue('1' in message)

    def test_reviewers_message_no_added(self):
        message = self.adapter.reviewers_updated([], [1])

        self.assertFalse('Added' in message)
        self.assertTrue('Removed' in message)
        self.assertTrue('1' in message)

    def test_reviewers_message_both(self):
        message = self.adapter.reviewers_updated([1], [2])

        self.assertTrue('Added' in message)
        self.assertTrue('Removed' in message)
        self.assertTrue('1' in message)
        self.assertTrue('2' in message)


class TestSlackAdapter(TestCase):
    target_url = 'https://my-slack-backend.com/incoming/my-very-secret-key'
    target_room = '<ROOM ID>'

    @override_settings(
        SLACK_DESTINATION_URL=target_url,
        SLACK_DESTINATION_ROOM=None,
    )
    @responses.activate
    def test_cant_send_with_no_room(self):
        adapter = SlackAdapter()
        adapter.send_message('my message', '')
        self.assertEqual(len(responses.calls), 0)

    @override_settings(
        SLACK_DESTINATION_URL=None,
        SLACK_DESTINATION_ROOM=target_room,
    )
    @responses.activate
    def test_cant_send_with_no_url(self):
        adapter = SlackAdapter()
        adapter.send_message('my message', '')
        self.assertEqual(len(responses.calls), 0)

    @override_settings(
        SLACK_DESTINATION_URL=target_url,
        SLACK_DESTINATION_ROOM=target_room,
    )
    @responses.activate
    def test_correct_payload(self):
        responses.add(responses.POST, self.target_url, status=200)
        adapter = SlackAdapter()
        message = 'my message'
        adapter.send_message(message, '')
        self.assertEqual(len(responses.calls), 1)
        self.assertDictEqual(
            json.loads(responses.calls[0].request.body),
            {
                'room': self.target_room,
                'message': message,
            }
        )

    @responses.activate
    def test_gets_lead_if_slack_set(self):
        adapter = SlackAdapter()
        submission = ApplicationSubmissionFactory()
        recipients = adapter.recipients(MESSAGES.COMMENT, submission)
        self.assertTrue(submission.lead.slack in recipients[0])

    @responses.activate
    def test_gets_black_if_slack_not_set(self):
        adapter = SlackAdapter()
        submission = ApplicationSubmissionFactory(lead__slack='')
        recipients = adapter.recipients(MESSAGES.COMMENT, submission)
        self.assertTrue(submission.lead.slack in recipients[0])


@override_settings(SEND_MESSAGES=True)
class TestEmailAdapter(AdapterMixin, TestCase):
    adapter = EmailAdapter()

    def test_email_new_submission(self):
        submission = ApplicationSubmissionFactory()
        self.adapter_process(MESSAGES.NEW_SUBMISSION, submission=submission)

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [submission.user.email])

    def test_no_email_private_comment(self):
        comment = CommentFactory(internal=True)

        self.adapter_process(MESSAGES.COMMENT, comment=comment, submission=comment.submission)
        self.assertEqual(len(mail.outbox), 0)

    def test_no_email_own_comment(self):
        application = ApplicationSubmissionFactory()
        comment = CommentFactory(user=application.user, submission=application)

        self.adapter_process(MESSAGES.COMMENT, comment=comment, user=comment.user, submission=comment.submission)
        self.assertEqual(len(mail.outbox), 0)

    def test_reviewers_email(self):
        reviewers = ReviewerFactory.create_batch(4)
        submission = ApplicationSubmissionFactory(status='external_review', reviewers=reviewers, workflow_stages=2)
        self.adapter_process(MESSAGES.READY_FOR_REVIEW, submission=submission)

        self.assertEqual(len(mail.outbox), 4)
        self.assertTrue(mail.outbox[0].subject, 'ready to review')
