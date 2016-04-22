Hyper-h2 is written and maintained by Cory Benfield and various contributors:

Development Lead
````````````````

- Cory Benfield <cory@lukasa.co.uk>

Contributors
````````````

In chronological order:

- Robert Collins (@rbtcollins)

  - Provided invaluable and substantial early input into API design and layout.
  - Added code preventing ``Proxy-Authorization`` from getting added to HPACK
    compression contexts.

- Maximilian Hils (@maximilianhils)

  - Added asyncio example.

- Alex Chan (@alexwlchan)

  - Fixed docstring, added URLs to README.

- Glyph Lefkowitz (@glyph)

  - Improved example Twisted server.

- Thomas Kriechbaumer (@Kriechi)

  - Fixed incorrect arguments being passed to ``StreamIDTooLowError``.

- WeiZheng Xu (@boyxuper)

  - Reported a bug relating to hyper-h2's updating of the connection window in
    response to SETTINGS_INITIAL_WINDOW_SIZE.

- Evgeny Tataurov (@etataurov)

  - Added the ``additional_data`` field to the ``ConnectionTerminated`` event.

- Brett Cannon (@brettcannon)

  - Changed Travis status icon to SVG.
  - Documentation improvements.

- Felix Yan (@felixonmars)

  - Widened allowed version numbers of enum34.
  - Updated test requirements.

- Keith Dart (@kdart)

  - Fixed curio example server flow control problems.

- Gil Gonçalves (@LuRsT)

  - Added code forbidding non-RFC 7540 pseudo-headers.
