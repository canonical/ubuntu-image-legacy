"""Bootstrap phases."""


def phase1(unpack_dir, channel, model):
    # We don't actually have to parse the model assertion.  We just have to
    # pass it to `snap bootstrap`.
    print('gadget-unpack-dir:', unpack_dir)
    print('channel:', channel)
    print('model assertion:', model)
