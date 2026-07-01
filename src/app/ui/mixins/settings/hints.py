"""Quality nudges and output filename preview."""

from __future__ import annotations

from app.profiles import (
    audio_stream_copyable,
    can_stream_copy_audio_to_mp4,
    can_stream_copy_to_mp4,
    descriptive_output_stem,
    estimate_compress_plan,
    estimate_split_parts,
    is_original_4k,
    should_nudge_split_instead,
    should_warn_quality_loss,
    single_output_filename,
    source_video_bitrate_kbps,
    split_remux_is_redundant,
)


class SettingHintsMixin:
    def _update_nudges(self) -> None:
        if not self.video_info:
            self.nudge_label.configure(text="")
            return

        v = self.video_info
        mb = self.limit_mb.get()
        res = self.resolution.get()  # type: ignore[assignment]
        split_parts = estimate_split_parts(v.file_size, mb)
        source_kbps = source_video_bitrate_kbps(v.bitrate, v.duration, v.file_size)
        br = self.bitrate_mode.get()  # type: ignore[assignment]
        nudge = ""

        if (
            self.mode.get() == "split"
            and not self.allow_split.get()
            and split_remux_is_redundant(v)
        ):
            nudge = (
                "Source is already a Discord-compatible MP4 — remux would not change anything. "
                "Pick a file size limit or Compress instead."
            )
        elif self.mode.get() != "split" and br == "source":
            nudge = (
                "Source bitrate — matches input quality; files may be as large as split-only."
            )
        elif (
            self.mode.get() != "split"
            and should_warn_quality_loss(
                source_kbps,
                res,
                self.codec.get(),  # type: ignore[arg-type]
                v.height,
                br,
            )
        ):
            nudge = (
                "Bitrate is much lower than source — expect visible quality loss. "
                "Try Super High, High, or Source, or use Split only."
            )
        elif self.mode.get() != "split" and is_original_4k(res, v.height):
            nudge = (
                "4K source at original resolution — files stay large. "
                "Consider 1080p for smaller uploads."
            )
        elif (
            self.mode.get() != "split"
            and self.allow_split.get()
            and should_nudge_split_instead(
                v.file_size,
                v.duration,
                res,
                self.codec.get(),  # type: ignore[arg-type]
                source_kbps,
                v.height,
                br,
            )
        ):
            nudge = (
                "Source is already efficiently encoded — Split only avoids a larger re-encode."
            )
        elif self.mode.get() == "split" and not can_stream_copy_to_mp4(v.video_codec):
            nudge = (
                f"Video codec '{v.video_codec}' cannot split to Discord MP4 — "
                "pick H.264 or HEVC above."
            )
        elif (
            self.mode.get() == "split"
            and v.audio_codec
            and not audio_stream_copyable(
                v.audio_codec, v.audio_channels, v.audio_sample_rate
            )
        ):
            if not can_stream_copy_audio_to_mp4(v.audio_codec):
                nudge = (
                    f"Audio codec '{v.audio_codec}' will be converted to AAC when splitting."
                )
            else:
                nudge = (
                    "Audio will be remuxed to AAC when splitting "
                    "(source audio metadata is incomplete)."
                )
        elif split_parts > 8 and self.mode.get() == "split" and self.allow_split.get():
            nudge = "Consider compressing — fewer parts to upload."
        self.nudge_label.configure(text=nudge)

    def _update_output_filename_hint(self) -> None:
        if not hasattr(self, "output_filename_hint"):
            return
        if not self.video_path:
            self.output_filename_hint.configure(
                text="Select a video to see an example filename."
            )
            return

        stem = self.video_path.stem
        mode = self.mode.get()  # type: ignore[assignment]
        if self.descriptive_filenames.get() and self.video_info:
            stem = descriptive_output_stem(
                stem,
                self.resolution.get(),  # type: ignore[arg-type]
                self.video_info.height,
                mode,
                self.codec.get(),  # type: ignore[arg-type]
                self.bitrate_mode.get(),  # type: ignore[arg-type]
                allow_split=self.allow_split.get(),
            )

        if not self.allow_split.get():
            example = single_output_filename(stem, mode)  # type: ignore[arg-type]
        elif mode == "compress":
            example = f"{stem}_compressed.mp4"
        else:
            example = f"{stem}_part001.mp4"
            if self.video_info and self.allow_split.get():
                mb = self.limit_mb.get()
                v = self.video_info
                if mode == "split":
                    parts = estimate_split_parts(v.file_size, mb)
                else:
                    parts, _ = estimate_compress_plan(
                        v.duration,
                        self.resolution.get(),  # type: ignore[arg-type]
                        self.codec.get(),  # type: ignore[arg-type]
                        mb,
                        source_video_bitrate_kbps(v.bitrate, v.duration, v.file_size),
                        v.height,
                        self.bitrate_mode.get(),  # type: ignore[arg-type]
                    )
                if parts > 1:
                    example += f"  (+ {parts - 1} more)"

        self.output_filename_hint.configure(text=f"Example: {example}")
