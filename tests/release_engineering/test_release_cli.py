"""Regression tests for the real release operator, including hostile archives."""
import importlib.util,io,json,os,stat,tarfile,tempfile,unittest
from pathlib import Path
from unittest.mock import patch

MOD=Path(__file__).resolve().parents[2]/'packaging/release_cli.py'
if not MOD.exists():MOD=Path(__file__).with_name('release_cli.py')
spec=importlib.util.spec_from_file_location('bnn_release',MOD);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class ReleaseEngineering(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def test_confined_child(self):self.assertEqual(m.confined(self.root/'new',self.root),(self.root/'new').resolve())
    def test_confined_parent_denied(self):
        with self.assertRaises(PermissionError):m.confined(self.root.parent,self.root)
    def test_confined_equal_denied(self):
        with self.assertRaises(PermissionError):m.confined(self.root,self.root)
    def test_confined_symlink_escape(self):
        (self.root/'link').symlink_to(self.root.parent)
        with self.assertRaises(PermissionError):m.confined(self.root/'link'/'out',self.root)
    def test_manifest_roundtrip(self):
        (self.root/'a').write_text('test');expected=m.inventory(self.root);m.write(self.root/'bundle-manifest.json',{'objects':expected});self.assertEqual(m.verify_tree(self.root),1)
    def test_changed_byte_rejected(self):
        (self.root/'a').write_text('test');m.write(self.root/'bundle-manifest.json',{'objects':m.inventory(self.root)});(self.root/'a').write_text('changed')
        with self.assertRaises(PermissionError):m.verify_tree(self.root)
    def test_added_file_rejected(self):
        m.write(self.root/'bundle-manifest.json',{'objects':{}});(self.root/'extra').write_text('x')
        with self.assertRaises(PermissionError):m.verify_tree(self.root)
    def test_changed_mode_rejected(self):
        (self.root/'a').write_text('x');(self.root/'a').chmod(0o600);m.write(self.root/'bundle-manifest.json',{'objects':m.inventory(self.root)});(self.root/'a').chmod(0o700)
        with self.assertRaises(PermissionError):m.verify_tree(self.root)
    def test_unlocked_manifest_rejected(self):
        m.write(self.root/'bundle-manifest.json',{'objects':{}})
        with self.assertRaises(PermissionError):m.verify_tree(self.root,'0'*64)
    def member(self,name,kind=None,link=None):
        item=tarfile.TarInfo(name)
        if kind:item.type=kind
        if link:item.linkname=link
        return item
    def test_archive_parent_traversal(self):
        with self.assertRaises(PermissionError):m.safe_member(self.member('Hermes-BNN-Full/../../outside'),self.root)
    def test_archive_absolute(self):
        with self.assertRaises(PermissionError):m.safe_member(self.member('/tmp/out'),self.root)
    def test_archive_wrong_root(self):
        with self.assertRaises(PermissionError):m.safe_member(self.member('Other/a'),self.root)
    def test_archive_absolute_symlink(self):
        with self.assertRaises(PermissionError):m.safe_member(self.member('Hermes-BNN-Full/a',tarfile.SYMTYPE,'/tmp/out'),self.root)
    def test_archive_symlink_escape(self):
        with self.assertRaises(PermissionError):m.safe_member(self.member('Hermes-BNN-Full/a',tarfile.SYMTYPE,'../out'),self.root)
    def test_archive_special_object(self):
        with self.assertRaises(PermissionError):m.safe_member(self.member('Hermes-BNN-Full/fifo',tarfile.FIFOTYPE),self.root)
    def test_archive_privileged_mode(self):
        i=self.member('Hermes-BNN-Full/a');i.mode=0o4755
        with self.assertRaises(PermissionError):m.safe_member(i,self.root)
    def test_archive_valid_internal_symlink(self):
        i=m.safe_member(self.member('Hermes-BNN-Full/bin/python',tarfile.SYMTYPE,'../runtime/python'),self.root);self.assertEqual(i.linkname,'../runtime/python')
    def test_archive_extract_preserves_executable_and_bytes(self):
        archive=self.root/'good.tar.gz'
        with tarfile.open(archive,'w:gz') as t:
            i=self.member('Hermes-BNN-Full/run');i.size=3;i.mode=0o755;t.addfile(i,io.BytesIO(b'run'))
        out=m.unarchive(archive,self.root/'new');self.assertEqual((out/'run').read_bytes(),b'run');self.assertEqual(stat.S_IMODE((out/'run').stat().st_mode),0o755)
    def test_existing_install_target_denied(self):
        with self.assertRaises(FileExistsError):m.unarchive(self.root/'missing',self.root)
    def test_credentials_stripped_from_child(self):
        with patch.dict(os.environ,{'OPENAI_API_KEY':'synthetic-never-forward','TELEGRAM_BOT_TOKEN':'synthetic-never-forward','PYTHONPATH':'/bad','HERMES_HOME':'/bad'},clear=True):
            e=m.clean_environment(self.root);self.assertFalse(any(x in e for x in ['OPENAI_API_KEY','TELEGRAM_BOT_TOKEN','PYTHONPATH','HERMES_HOME']));self.assertEqual(e['HOME'],str(self.root))
    def test_build_uses_only_committed_source_projection(self):
        (self.root/'product').mkdir();(self.root/'product/known.py').write_text('pass');(self.root/'product/ignored.pyc').write_bytes(b'ignored')
        with patch.object(m,'ROOT',self.root),patch.object(m,'git',return_value='product/known.py\0'):
            self.assertEqual(m.committed_product_files(),[self.root/'product/known.py'])
    def test_dirty_tree_rejected(self):
        with patch.object(m,'git',return_value=' M tracked'):
            with self.assertRaises(PermissionError):m.clean_commit()
    def test_unknown_environment_rejected_before_io(self):
        with self.assertRaises(PermissionError):m.qualify(self.root,'production')
    def test_atomic_receipt_json(self):
        m.write(self.root/'status.json',{'complete':False});m.write(self.root/'status.json',{'complete':True});self.assertTrue(m.read(self.root/'status.json')['complete']);self.assertFalse((self.root/'status.json.pending').exists())

    def signed_release(self):
        import subprocess
        key=self.root/'key';subprocess.run(['/usr/bin/ssh-keygen','-q','-t','ed25519','-N','','-f',str(key)],check=True,capture_output=True)
        (self.root/'trust').mkdir();(self.root/'trust/allowed_signers').write_text('bnn-release '+key.with_suffix('.pub').read_text())
        (self.root/'artifact.tar.gz').write_bytes(b'synthetic-artifact')
        m.write(self.root/'RELEASE.json',{'archive':{'name':'artifact.tar.gz','sha256':m.digest(self.root/'artifact.tar.gz')}})
        m.sign_manifest(self.root/'RELEASE.json',key)
    def test_normalized_tarinfo_serializes(self):
        i=self.member('Hermes-BNN-Full/run');i.pax_headers={'mtime':'999'}
        result=m.normalized_tarinfo(i,123)
        self.assertEqual(result.mtime,123);self.assertEqual(result.uid,0);self.assertEqual(result.pax_headers,{})
        archive=self.root/'normalized.tar.gz'
        with tarfile.open(archive,'w:gz') as t:t.addfile(result)
        with tarfile.open(archive) as t:self.assertEqual(t.next().mtime,123)
    def test_real_directory_tar_add_and_extract(self):
        source=self.root/'source';source.mkdir();(source/'a').write_bytes(b'actual tar.add metadata');(source/'link').symlink_to('a')
        archive=self.root/'real.tar.gz'
        with tarfile.open(archive,'w:gz') as t:t.add(source,arcname='Hermes-BNN-Full',filter=lambda i:m.normalized_tarinfo(i,123))
        out=m.unarchive(archive,self.root/'restored');self.assertEqual((out/'link').read_bytes(),(source/'a').read_bytes())
    def test_signed_release_valid(self):
        self.signed_release()
        with patch.object(m,'ROOT',self.root):self.assertEqual(m.verify_release(self.root)['archive']['name'],'artifact.tar.gz')
    def test_signed_manifest_tamper_rejected(self):
        import subprocess
        self.signed_release();(self.root/'RELEASE.json').write_text('{}')
        with patch.object(m,'ROOT',self.root):
            with self.assertRaises(subprocess.CalledProcessError):m.verify_release(self.root)
    def test_signed_archive_tamper_rejected(self):
        self.signed_release();(self.root/'artifact.tar.gz').write_bytes(b'changed')
        with patch.object(m,'ROOT',self.root):
            with self.assertRaises(PermissionError):m.verify_release(self.root)

if __name__=='__main__':unittest.main(verbosity=2)
