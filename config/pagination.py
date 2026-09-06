from rest_framework.pagination import PageNumberPagination


class StandardResultsPagination(PageNumberPagination):
    """Shared across every list endpoint that needs paging — a table that
    can realistically grow past a couple dozen rows (campaigns, users,
    contacts), not the small pools (sender IDs) that don't need it yet."""

    page_size = 25
    page_size_query_param = 'page_size'
    max_page_size = 100
