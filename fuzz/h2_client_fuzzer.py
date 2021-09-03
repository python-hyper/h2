#!/usr/bin/env python
import atheris
import sys

with atheris.instrument_imports():
  import h2.connection
  import h2.config
  from h2.exceptions import ProtocolError, FrameDataMissingError

def TestOneInput(data):
  config = h2.config.H2Configuration(client_side=True)
  conn = h2.connection.H2Connection(config=config)
  conn.initiate_connection()
  headers = [
    (u':authority', u'example.com'),
    (u':path', u'/'),
    (u':scheme', u'https'),
    (u':method', u'GET'),
  ]
  conn.send_headers(1, headers=headers, end_stream=True)
  try:
    conn.receive_data(data)
  except ProtocolError:
    pass

if __name__ == "__main__":
  atheris.Setup(sys.argv, TestOneInput)
  atheris.Fuzz()