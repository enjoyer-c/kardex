import cv2
import os
from datetime import datetime
import glob

def find_ssd_path():
    user = os.getenv('USER') or os.getenv('USERNAME') or 'pi'
    media_dir = f"/media/{user}"
    
    if os.path.exists(media_dir):
        drives = [d for d in os.listdir(media_dir) if os.path.isdir(os.path.join(media_dir, d))]
        if drives:
            return os.path.join(media_dir, drives[0])
            
    return "/mnt/kardex_ssd"

def capture_to_ssd(max_tested=5):
    ssd_root = find_ssd_path()
    base_dir = os.path.join(ssd_root, "kardex_ssd", "test_capture_kardex")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = os.path.join(base_dir, f"capture_{timestamp}")
    
    try:
        os.makedirs(output_dir, exist_ok=True)
    except Exception as e:
        print(f"[Fehler] Konnte Ordner auf der SSD nicht erstellen: {e}")
        print("Bitte prüfen, ob die SSD schreibgeschützt ist oder ob sie wirklich verbunden ist.")
        return
    
    active_cams = 0
    print(f"Suche nach USB-Cams... Speichern nach: {output_dir}")
    
    for index in range(max_tested):
        cap = cv2.VideoCapture(index, cv2.CAP_V4L2)
        
        if not cap.isOpened():
            cap.release()
            continue
            
        for _ in range(5):
            cap.read()
            
        ret, frame = cap.read()
        
        if ret:
            active_cams += 1
            filename = os.path.join(output_dir, f"kamera_{index}.jpg")
            cv2.imwrite(filename, frame)
            print(f"[Erfolg] Bild von Kamera {index} gespeichert: {filename}")
        else:
            print(f"[Warnung] Kamera {index} gefunden, aber kein Bild erhalten.")
            
        cap.release()
        
    print(f"\nFertig! {active_cams} USB-Kamera(s) verarbeitet.")

if __name__ == "__main__":
    capture_to_ssd()