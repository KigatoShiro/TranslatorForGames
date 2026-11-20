import shutil, sys, tempfile, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import motorfest_tweaker as mt  # noqa: E402


class TweakerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        for f in (HERE / "sample").glob("*.xml"):
            shutil.copy(f, self.tmp / f.name)
        self.cfg = self.tmp / "GameSettings.xml"

    def tearDown(self):
        mt.set_readonly(list(self.tmp.glob("*.xml")), False)
        shutil.rmtree(self.tmp)

    def run_cli(self, *a):
        return mt.main(["--dir", str(self.tmp), *a])

    def test_clean_image(self):
        self.run_cli("apply", "clean_image")
        raw = self.cfg.read_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"), "BOM сохранён")
        t = raw.decode("utf-8-sig")
        self.assertIn('MotionBlur="false"', t)
        self.assertIn('ChromaticAberration="0"', t)
        self.assertIn('DepthOfField="0"', t)
        self.assertIn("<FilmGrain>0</FilmGrain>", t)
        self.assertIn('Name="Vignette" Value="Off"', t)
        self.assertIn('Name="Denoiser" Value="1"', t, "exclude работает")
        self.assertIn('<!-- fake sample for tests MotionBlur="1" -->', t, "комментарии не трогаются")
        self.assertIn('VSync="True"', t)
        # Bindings не трогаем
        self.assertIn('MotionBlur="true"', (self.tmp / "Bindings_d09bf528.xml").read_text("utf-8-sig"))

    def test_fps_fov(self):
        self.run_cli("apply", "fps_unlock", "fov_max")
        t = self.cfg.read_text("utf-8-sig")
        self.assertIn('VSync="False"', t)
        self.assertIn('FrameRateLimit="0"', t)
        self.assertIn('FieldOfView="1.000"', t)
        self.assertIn('FovMin="0.0" FovMax="1.0"', t)

    def test_dry_run_and_restore(self):
        before = self.cfg.read_bytes()
        self.run_cli("apply", "clean_image", "--dry-run")
        self.assertEqual(before, self.cfg.read_bytes())
        self.run_cli("set", "FrameRateLimit=144")
        self.assertIn('FrameRateLimit="144"', self.cfg.read_text("utf-8-sig"))
        self.run_cli("restore")
        self.assertEqual(before, self.cfg.read_bytes())

    def test_lock(self):
        import os
        self.run_cli("lock")
        self.assertFalse(os.stat(self.cfg).st_mode & 0o222)
        self.run_cli("set", "FrameRateLimit=120")  # запись всё равно проходит
        self.assertIn('FrameRateLimit="120"', self.cfg.read_text("utf-8-sig"))
        self.assertFalse(os.stat(self.cfg).st_mode & 0o222, "замок сохранён")
        self.run_cli("unlock")
        self.assertTrue(os.access(self.cfg, os.W_OK))


class DiffTest(TweakerTest):
    def test_snapshot_diff(self):
        import io, contextlib
        self.run_cli("snapshot")
        t = self.cfg.read_text("utf-8-sig").replace('FrameRateLimit="60"', 'FrameRateLimit="144"')
        self.cfg.write_text(t, "utf-8-sig")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.run_cli("diff")
        out = buf.getvalue()
        self.assertIn("GameSettings.xml", out)
        self.assertIn("Graphics.FrameRateLimit", out)
        self.assertIn("60 -> 144", out)
        self.assertNotIn("Bindings", out)


if __name__ == "__main__":
    unittest.main()
