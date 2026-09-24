"""Sources fetch raw material and normalize it into the record shape an adapter
parses. Keeping fetch separate from parse means the same adapter serves a live
API and an offline dataset export, and that network access stays out of the
mapping logic where it would make every test need a socket.
"""
