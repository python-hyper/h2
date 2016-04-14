# -*- coding: utf-8 -*-
"""
h2/utilities
~~~~~~~~~~~~

Utility functions that do not belong in a separate module.
"""
import re

from .exceptions import ProtocolError, FlowControlError

UPPER_RE = re.compile("[A-Z]")

# A set of headers that are hop-by-hop or connection-specific and thus
# forbidden in HTTP/2. This list comes from RFC 7540 § 8.1.2.2.
CONNECTION_HEADERS = set([
    'connection',
    'proxy-connection',
    'keep-alive',
    'transfer-encoding',
    'upgrade',
])


_ALLOWED_PSEUDO_HEADER_FIELDS = set([
    ':method',
    ':scheme',
    ':authority',
    ':path',
    ':status',
])


def is_informational_response(headers):
    """
    Searches a header block for a :status header to confirm that a given
    collection of headers are an informational response. Assumes the header
    block is well formed: that is, that the HTTP/2 special headers are first
    in the block, and so that it can stop looking when it finds the first
    header field whose name does not begin with a colon.

    :param headers: The HTTP/2 header block.
    :returns: A boolean indicating if this is an informational response.
    """
    for n, v in headers:
        if isinstance(n, bytes):
            sigil = b':'
            status = b':status'
            informational_start = b'1'
        else:
            sigil = u':'
            status = u':status'
            informational_start = u'1'

        # If we find a non-special header, we're done here: stop looping.
        if not n.startswith(sigil):
            return False

        # This isn't the status header, bail.
        if n != status:
            continue

        # If the first digit is a 1, we've got informational headers.
        return v.startswith(informational_start)


def guard_increment_window(current, increment):
    """
    Increments a flow control window, guarding against that window becoming too
    large.

    :param current: The current value of the flow control window.
    :param increment: The increment to apply to that window.
    :returns: The new value of the window.
    :raises: ``FlowControlError``
    """
    # The largest value the flow control window may take.
    LARGEST_FLOW_CONTROL_WINDOW = 2**31 - 1

    new_size = current + increment

    if new_size > LARGEST_FLOW_CONTROL_WINDOW:
        raise FlowControlError(
            "May not increment flow control window past %d" %
            LARGEST_FLOW_CONTROL_WINDOW
        )

    return new_size


def validate_headers(headers):
    """
    Validates a header sequence against a set of constraints from RFC 7540.
    """
    # This validation logic is built on a sequence of generators that are
    # iterated over to provide the final header list. This reduces some of the
    # overhead of doing this checking. However, it's worth noting that this
    # checking remains somewhat expensive, and attempts should be made wherever
    # possible to reduce the time spent doing them.
    #
    # For example, we avoid tuple upacking in loops because it represents a
    # fixed cost that we don't want to spend, instead indexing into the header
    # tuples.
    headers = _reject_uppercase_header_fields(headers)
    headers = _reject_te(headers)
    headers = _reject_connection_header(headers)
    headers = _reject_pseudo_header_fields(headers)
    return list(headers)


def _reject_uppercase_header_fields(headers):
    """
    Raises a ProtocolError if any uppercase character is found in a header
    block.
    """
    for header in headers:
        if UPPER_RE.search(header[0]):
            raise ProtocolError(
                "Received uppercase header name %s." % header[0])
        yield header


def _reject_te(headers):
    """
    Raises a ProtocolError if the TE header is present in a header block and
    its value is anything other than "trailers".
    """
    for header in headers:
        if header[0] == 'te':
            if header[1].lower().strip() != 'trailers':
                raise ProtocolError(
                    "Invalid value for Transfer-Encoding header: %s" %
                    header[1]
                )

        yield header


def _reject_connection_header(headers):
    """
    Raises a ProtocolError if the Connection header is present in a header
    block.
    """
    for header in headers:
        if header[0] in CONNECTION_HEADERS:
            raise ProtocolError(
                "Connection-specific header field present: %s." % header[0]
            )

        yield header


def _reject_pseudo_header_fields(headers):
    """
    Raises a ProtocolError if duplicate pseudo-header fields are found in a
    header block or if a pseudo-header field arrives in a block after an
    ordinary header field.
    """
    seen_pseudo_header_fields = set()
    seen_regular_header = False

    for header in headers:
        if header[0].startswith(':'):
            if header[0] in seen_pseudo_header_fields:
                raise ProtocolError(
                    "Received duplicate pseudo-header field %s" % header[0]
                )

            seen_pseudo_header_fields.add(header[0])

            if seen_regular_header:
                raise ProtocolError(
                    "Received pseudo-header field out of sequence: %s" %
                    header[0]
                )

            if header[0] not in _ALLOWED_PSEUDO_HEADER_FIELDS:
                raise ProtocolError(
                    "Received custom pseudo-header field %s" % header[0]
                )

        else:
            seen_regular_header = True

        yield header
