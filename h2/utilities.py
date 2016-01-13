# -*- coding: utf-8 -*-
"""
h2/utilities
~~~~~~~~~~~~

Utility functions that do not belong in a separate module.
"""
import re

from .exceptions import ProtocolError

UPPER_RE = re.compile("[A-Z]")


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
    headers = reject_connection_header(headers)
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


def reject_connection_header(headers):
    """
    Raises a ProtocolError if the Connection header is present in a header
    block.
    """
    for header in headers:
        if header[0] == 'connection':
            raise ProtocolError("Connection header field present.")

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
        else:
            seen_regular_header = True

        yield header
