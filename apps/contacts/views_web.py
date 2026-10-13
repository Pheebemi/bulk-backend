"""Server-rendered Contacts pages — shared by the customer app and the
admin console (each scoped to request.user's own groups, exactly like the
API: admin's groups are separate from any customer's)."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import models
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounts.web_utils import staff_required

from .models import Contact, ContactGroup
from .views import import_contacts_csv

SCOPES = {
    'user': {
        'base': 'layout/user_shell.html',
        'home': 'web-contacts',
        'group': 'web-contact-group',
        'group_delete': 'web-contact-group-delete',
        'contact_edit': 'web-contact-edit',
        'contact_delete': 'web-contact-delete',
    },
    'console': {
        'base': 'layout/admin_shell.html',
        'home': 'console-contacts',
        'group': 'console-contact-group',
        'group_delete': 'console-contact-group-delete',
        'contact_edit': 'console-contact-edit',
        'contact_delete': 'console-contact-delete',
    },
}


def scoped(view):
    """Applies the right auth decorator for the URL's scope."""
    def wrapper(request, scope, *args, **kwargs):
        guard = staff_required if scope == 'console' else login_required(login_url='web-login')
        return guard(view)(request, scope, *args, **kwargs)
    wrapper.__name__ = view.__name__
    return wrapper


@scoped
def contacts_home(request, scope):
    names = SCOPES[scope]
    if request.method == 'POST':
        if request.FILES.get('file'):
            f = request.FILES['file']
            group = import_contacts_csv(request.user, f, request.POST.get('group_name', '').strip())
            messages.success(request, f'{f.name} imported.')
            return redirect(names['group'], pk=group.pk)
        name = request.POST.get('group_name', '').strip()
        if not name:
            messages.error(request, 'Enter a group name first.')
        else:
            group = ContactGroup.objects.create(user=request.user, name=name[:100])
            messages.success(request, f'"{group.name}" created.')
            return redirect(names['group'], pk=group.pk)
    groups = ContactGroup.objects.filter(user=request.user).annotate(n=models.Count('contacts')).order_by('-created_at')
    return render(request, 'contacts/home.html', {'groups': groups, 'names': names, 'scope': scope})


@scoped
def group_detail(request, scope, pk):
    names = SCOPES[scope]
    group = get_object_or_404(ContactGroup, pk=pk, user=request.user)
    if request.method == 'POST':
        phone = request.POST.get('phone_number', '').strip()
        if not phone:
            messages.error(request, 'Enter a phone number first.')
        else:
            Contact.objects.create(
                group=group, phone_number=phone[:15],
                first_name=request.POST.get('first_name', '').strip()[:50],
                last_name=request.POST.get('last_name', '').strip()[:50],
            )
            messages.success(request, 'Contact added.')
        return redirect(names['group'], pk=group.pk)
    page = Paginator(group.contacts.order_by('id'), 50).get_page(request.GET.get('page'))
    return render(request, 'contacts/group.html', {'group': group, 'page': page, 'names': names, 'scope': scope})


@scoped
def group_delete(request, scope, pk):
    group = get_object_or_404(ContactGroup, pk=pk, user=request.user)
    if request.method == 'POST':
        group.delete()
        messages.success(request, 'Group deleted.')
    return redirect(SCOPES[scope]['home'])


@scoped
def contact_edit(request, scope, group_pk, pk):
    contact = get_object_or_404(Contact, pk=pk, group_id=group_pk, group__user=request.user)
    if request.method == 'POST':
        phone = request.POST.get('phone_number', '').strip()
        if not phone:
            messages.error(request, 'Phone number cannot be empty.')
        else:
            contact.first_name = request.POST.get('first_name', '').strip()[:50]
            contact.last_name = request.POST.get('last_name', '').strip()[:50]
            contact.phone_number = phone[:15]
            contact.save()
            messages.success(request, 'Contact updated.')
    return redirect(SCOPES[scope]['group'], pk=group_pk)


@scoped
def contact_delete(request, scope, group_pk, pk):
    contact = get_object_or_404(Contact, pk=pk, group_id=group_pk, group__user=request.user)
    if request.method == 'POST':
        contact.delete()
        messages.success(request, 'Contact deleted.')
    return redirect(SCOPES[scope]['group'], pk=group_pk)
