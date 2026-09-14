import os
import re
import sys
import getpass
import time

import hou
import husd.outputprocessor as base

PARAM_PACKAGE_ROOT = 'portablereferences_package_root'
CASE_INSENSITIVE = sys.platform.startswith('win')
_WINDOWS_DRIVE_ROOT_RE = re.compile(r'^[A-Za-z]:$')
_VERSION_DIR_RE = re.compile(r'^v\d+$', re.IGNORECASE)


def _normalize(path):
    if not path:
        return ''
    return hou.text.normpath(path).replace('\\', '/').rstrip('/')


def _match_key(path):
    return path.casefold() if CASE_INSENSITIVE else path


class PortableReferences(base.OutputProcessor):

    def __init__(self):
        super().__init__()
        self.output_dir = ''
        self.package_root = ''
        self.package_root_key = ''

    @staticmethod
    def name():
        return 'portablereferences'

    @staticmethod
    def displayName():
        return 'Portable References'

    @staticmethod
    def parameters():
        group = hou.ParmTemplateGroup()
        group.append(hou.StringParmTemplate(
            PARAM_PACKAGE_ROOT,
            'Package Root',
            1,
            default_value=('',),
            string_type=hou.stringParmType.FileReference,
            file_type=hou.fileType.Directory,
            help=(
                'Package Root boundary. References inside this directory will be '
                'converted to relative paths (e.g. "../modelDefault/..."). '
                'If empty, auto-detects version folders (v###) and uses parent directory.'
            )
        ))
        return group.asDialogScript()

    def beginSave(self, config_node, config_overrides, lop_node, t, stage_variables):
        super().beginSave(config_node, config_overrides, lop_node, t, stage_variables)
        self.output_usd = self.evalConfig('lopoutput', config_node, config_overrides, t)
        output_dir, _ = os.path.split(self.output_usd) if self.output_usd else ('', '')
        self.output_dir = _normalize(output_dir)

        # 讀取使用者手動指定的 Package Root
        raw_package_root = self.evalConfig(PARAM_PACKAGE_ROOT, config_node, config_overrides, t) or ''
        expanded_pkg_root = hou.text.expandString(raw_package_root).strip() if raw_package_root else ''

        if expanded_pkg_root:
            normalized_pkg_root = _normalize(expanded_pkg_root)
            if not normalized_pkg_root or _WINDOWS_DRIVE_ROOT_RE.match(normalized_pkg_root):
                raise ValueError('Filesystem root cannot be used as Package Root')
            self.package_root = normalized_pkg_root
        elif self.output_dir:
            # 自動推導：若 output_dir 是版本目錄 (如 .../chair/v002)，自動使用其上一層 (.../chair) 為 Package Root
            parent_dir, leaf = os.path.split(self.output_dir)
            if _VERSION_DIR_RE.match(leaf) and parent_dir and not _WINDOWS_DRIVE_ROOT_RE.match(parent_dir):
                self.package_root = _normalize(parent_dir)
            else:
                self.package_root = self.output_dir
        else:
            self.package_root = ''

        self.package_root_key = _match_key(self.package_root.rstrip('/') + '/') if self.package_root else ''

    def processReferencePath(self, asset_path, referencing_layer_path, asset_is_layer):
        # Python procedurals 由 USD plugin 解析，非檔案路徑，予以跳過
        if asset_path.endswith('.py'):
            return asset_path

        if not self.output_dir or not self.package_root:
            return asset_path

        # 展開並正規化絕對路徑
        abs_asset_path = hou.text.normpath(hou.text.abspath(asset_path, self.output_dir)).replace('\\', '/')
        abs_asset_key = _match_key(abs_asset_path)

        # 判斷是否落在 Package Root 邊界範圍內
        if not abs_asset_key.startswith(self.package_root_key):
            return abs_asset_path

        # 在 Package Root 邊界內：輸出相對於當前 layer 的乾淨相對路徑
        # 同目錄或子目錄會輸出 ./layers/...，跨 sub-object 向上跳層會輸出 ../modelDefault/...
        rel_path = hou.text.relpath(abs_asset_path, referencing_layer_path).replace('\\', '/')
        return rel_path

    def processSavePath(self, asset_path, referencing_layer_path, asset_is_layer):
        if self.output_dir:
            return hou.text.abspath(asset_path, self.output_dir)
        return asset_path

    def processLayer(self, layer, layersavepath=None):
        layer_data = layer.customLayerData
        layer_data['hip_file'] = hou.hipFile.path()
        layer_data['create_time'] = time.ctime()
        layer_data['user'] = getpass.getuser()
        layer.customLayerData = layer_data
        return True


################################################################################
# In order to be considered for output processing, this python module
# implements the function that returns a processor object.
#
def usdOutputProcessor():
    return PortableReferences
