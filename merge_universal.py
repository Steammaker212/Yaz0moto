import os
import subprocess
import shutil

app_bundle = 'build/Yaz0moto.app'
intel_deps = 'intel_deps'

def get_arch(path):
    try:
        out = subprocess.check_output(['file', path]).decode()
        if 'universal' in out:
            return 'universal'
        if 'arm64' in out:
            return 'arm64'
        if 'x86_64' in out:
            return 'x86_64'
    except:
        pass
    return None

def find_intel_counterpart(path):
    # Try looking in intel_deps using the relative path from Contents/Resources/lib
    rel_lib_path = os.path.relpath(path, os.path.join(app_bundle, 'Contents/Resources/lib'))
    intel_path = os.path.join(intel_deps, rel_lib_path)
    if os.path.exists(intel_path):
        return intel_path
    
    # Try just the basename in intel_deps root (for some top level libs)
    intel_path = os.path.join(intel_deps, os.path.basename(path))
    if os.path.exists(intel_path):
        return intel_path
        
    return None

def merge_binaries():
    merged_count = 0
    for root, dirs, files in os.walk(app_bundle):
        for file in files:
            if file.endswith('.so') or file.endswith('.dylib') or file == 'Python' or file == 'Yaz0moto':
                path = os.path.join(root, file)
                if os.path.islink(path): continue
                    
                arch = get_arch(path)
                if arch == 'arm64':
                    intel_path = find_intel_counterpart(path)
                    if intel_path:
                        arm_tmp = path + '.arm64'
                        shutil.copy(path, arm_tmp)
                        try:
                            # Use lipo to merge arm64 and x86_64
                            subprocess.run(['lipo', '-create', arm_tmp, intel_path, '-output', path], check=True)
                            os.remove(arm_tmp)
                            print(f"Merged: {path}")
                            merged_count += 1
                        except:
                            if os.path.exists(arm_tmp): os.remove(arm_tmp)
    
    print(f"Total merged: {merged_count}")

if __name__ == '__main__':
    merge_binaries()
    # Ad-hoc sign the final bundle
    print("Signing bundle...")
    subprocess.run(['codesign', '--force', '--deep', '--sign', '-', app_bundle], check=True)
    print("Done.")
