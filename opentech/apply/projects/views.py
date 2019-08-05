from copy import copy

from django.utils.decorators import method_decorator
from django.views.generic import DetailView, UpdateView

from opentech.apply.activity.messaging import MESSAGES, messenger
from opentech.apply.activity.views import ActivityContextMixin, CommentFormView
from opentech.apply.users.decorators import staff_required
from opentech.apply.utils.views import (DelegateableView, DelegatedViewMixin,
                                        ViewDispatcher)

from .forms import ProjectEditForm, SetPendingForm, UpdateProjectLeadForm
from .models import DocumentCategory, Project


@method_decorator(staff_required, name='dispatch')
class SendForApprovalView(DelegatedViewMixin, UpdateView):
    context_name = 'approval_form'
    form_class = SetPendingForm
    model = Project

    def form_valid(self, form):
        # lock project
        response = super().form_valid(form)

        messenger(
            MESSAGES.SEND_FOR_APPROVAL,
            request=self.request,
            user=self.request.user,
            source=form.instance.submission,
            project=form.instance,
        )

        return response


@method_decorator(staff_required, name='dispatch')
class UpdateLeadView(DelegatedViewMixin, UpdateView):
    model = Project
    form_class = UpdateProjectLeadForm
    context_name = 'lead_form'

    def form_valid(self, form):
        # Fetch the old lead from the database
        old = copy(self.get_object())

        response = super().form_valid(form)

        messenger(
            MESSAGES.UPDATE_PROJECT_LEAD,
            request=self.request,
            user=self.request.user,
            source=form.instance,
            related=old.lead or 'Unassigned',
        )

        return response


class AdminProjectDetailView(ActivityContextMixin, DelegateableView, DetailView):
    form_views = [
        SendForApprovalView,
        UpdateLeadView,
        CommentFormView,
    ]
    model = Project
    template_name_suffix = '_admin_detail'

    def get_context_data(self, **kwargs):
        return super().get_context_data(
            remaining_document_categories=DocumentCategory.objects.all(),
            **kwargs,
        )


class ApplicantProjectDetailView(DetailView):
    model = Project


class ProjectDetailView(ViewDispatcher):
    admin_view = AdminProjectDetailView
    applicant_view = ApplicantProjectDetailView


@method_decorator(staff_required, name='dispatch')
class ProjectEditView(UpdateView):
    form_class = ProjectEditForm
    model = Project
