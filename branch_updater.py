# Copyright (C) 2009 Canonical Ltd
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""An object that updates a bunch of branches based on data imported."""


from bzrlib import bzrdir, errors
from bzrlib.trace import error, note
import helpers


class BranchUpdater(object):

    def __init__(self, repo, branch, cache_mgr, heads_by_ref, last_ref, tags):
        """Create an object responsible for updating branches.

        :param heads_by_ref: a dictionary where
          names are git-style references like refs/heads/master;
          values are one item lists of commits marks.
        """
        self.repo = repo
        self.branch = branch
        self.cache_mgr = cache_mgr
        self.heads_by_ref = heads_by_ref
        self.last_ref = last_ref
        self.tags = tags

    def update(self):
        """Update the Bazaar branches and tips matching the heads.

        If the repository is shared, this routine creates branches
        as required. If it isn't, warnings are produced about the
        lost of information.

        :return: updated, lost_heads where
          updated = the list of branches updated
          lost_heads = a list of (bazaar-name,revision) for branches that
            would have been created had the repository been shared
        """
        updated = []
        branch_tips, lost_heads = self._get_matching_branches()
        for br, tip in branch_tips:
            if self._update_branch(br, tip):
                updated.append(br)
        return updated, lost_heads

    def _get_matching_branches(self):
        """Get the Bazaar branches.

        :return: default_tip, branch_tips, lost_heads where
          default_tip = the last commit mark for the default branch
          branch_tips = a list of (branch,tip) tuples for other branches.
          lost_heads = a list of (bazaar-name,revision) for branches that
            would have been created had the repository been shared and
            everything succeeded
        """
        branch_tips = []
        lost_heads = []
        ref_names = self.heads_by_ref.keys()
        if self.branch is not None:
            trunk = self.select_trunk(ref_names)
            default_tip = self.heads_by_ref[trunk][0]
            branch_tips.append((self.branch, default_tip))
            ref_names.remove(trunk)

        # Convert the reference names into Bazaar speak
        bzr_names = self._get_bzr_names_from_ref_names(ref_names)

        # Policy for locating branches
        def dir_under_current(name, ref_name):
            # Using the Bazaar name, get a directory under the current one
            return name
        def dir_sister_branch(name, ref_name):
            # Using the Bazaar name, get a sister directory to the branch
            return osutils.pathjoin(self.branch.base, "..", name)
        if self.branch is not None:
            dir_policy = dir_sister_branch
        else:
            dir_policy = dir_under_current

        # Create/track missing branches
        shared_repo = self.repo.is_shared()
        for name in sorted(bzr_names.keys()):
            ref_name = bzr_names[name]
            tip = self.heads_by_ref[ref_name][0]
            if shared_repo:
                location = dir_policy(name, ref_name)
                try:
                    br = self.make_branch(location)
                    branch_tips.append((br,tip))
                    continue
                except errors.BzrError, ex:
                    error("ERROR: failed to create branch %s: %s",
                        location, ex)
            lost_head = self.cache_mgr.revision_ids[tip]
            lost_info = (name, lost_head)
            lost_heads.append(lost_info)
        return branch_tips, lost_heads

    def select_trunk(self, ref_names):
        """Given a set of ref names, choose one as the trunk."""
        for candidate in ['refs/heads/master']:
            if candidate in ref_names:
                return candidate
        # Use the last reference in the import stream
        return self.last_ref

    def make_branch(self, location):
        """Make a branch in the repository if not already there."""
        try:
            return bzrdir.BzrDir.open(location).open_branch()
        except errors.NotBranchError, ex:
            return bzrdir.BzrDir.create_branch_convenience(location)

    def _get_bzr_names_from_ref_names(self, ref_names):
        """Generate Bazaar branch names from import ref names.
        
        :return: a dictionary with Bazaar names as keys and
          the original reference names as values.
        """
        bazaar_names = {}
        for ref_name in sorted(ref_names):
            parts = ref_name.split('/')
            if parts[0] == 'refs':
                parts.pop(0)
            full_name = "--".join(parts)
            bazaar_name = parts[-1]
            if bazaar_name in bazaar_names:
                if parts[0] == 'remotes':
                    bazaar_name += ".remote"
                else:
                    bazaar_name = full_name
            bazaar_names[bazaar_name] = ref_name
        return bazaar_names

    def _update_branch(self, br, last_mark):
        """Update a branch with last revision and tag information.
        
        :return: whether the branch was changed or not
        """
        last_rev_id = self.cache_mgr.revision_ids[last_mark]
        revs = list(self.repo.iter_reverse_revision_history(last_rev_id))
        revno = len(revs)
        existing_revno, existing_last_rev_id = br.last_revision_info()
        changed = False
        if revno != existing_revno or last_rev_id != existing_last_rev_id:
            br.set_last_revision_info(revno, last_rev_id)
            changed = True
        # apply tags known in this branch
        my_tags = {}
        if self.tags:
            for tag,rev in self.tags.items():
                if rev in revs:
                    my_tags[tag] = rev
            if my_tags:
                br.tags._set_tag_dict(my_tags)
                changed = True
        if changed:
            tagno = len(my_tags)
            note("\t branch %s now has %d %s and %d %s", br.nick,
                revno, helpers.single_plural(revno, "revision", "revisions"),
                tagno, helpers.single_plural(tagno, "tag", "tags"))
        return changed