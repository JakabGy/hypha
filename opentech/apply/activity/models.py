from django.conf import settings
from django.db import models


class Activity(models.Model):
    timestamp = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL)
    application = models.ForeignKey('funds.ApplicationSubmission')
    message = models.TextField()
