from PIL import Image, ImageEnhance
import os

def rotate_image(image_path: str, degrees: int) -> bool:
    try:
        with Image.open(image_path) as img:
            img_rotated = img.rotate(-degrees, expand=True) # Pillow rotates counter-clockwise
            img_rotated.save(image_path)
        return True
    except Exception as e:
        print(f"Error rotating image: {e}")
        return False

def flip_image(image_path: str, horizontal: bool = True) -> bool:
    try:
        with Image.open(image_path) as img:
            if horizontal:
                img_flipped = img.transpose(Image.FLIP_LEFT_RIGHT)
            else:
                img_flipped = img.transpose(Image.FLIP_TOP_BOTTOM)
            img_flipped.save(image_path)
        return True
    except Exception as e:
        print(f"Error flipping image: {e}")
        return False

def adjust_image(image_path: str, brightness: float = 1.0, contrast: float = 1.0, saturation: float = 1.0) -> bool:
    try:
        with Image.open(image_path) as img:
            if brightness != 1.0:
                enhancer = ImageEnhance.Brightness(img)
                img = enhancer.enhance(brightness)
            if contrast != 1.0:
                enhancer = ImageEnhance.Contrast(img)
                img = enhancer.enhance(contrast)
            if saturation != 1.0:
                enhancer = ImageEnhance.Color(img)
                img = enhancer.enhance(saturation)
            img.save(image_path)
        return True
    except Exception as e:
        print(f"Error adjusting image: {e}")
        return False

def crop_image(image_path: str, save_path: str, box: tuple) -> bool:
    """ box is (left, upper, right, lower) """
    try:
        with Image.open(image_path) as img:
            cropped = img.crop(box)
            cropped.save(save_path)
        return True
    except Exception as e:
        print(f"Error cropping image: {e}")
        return False
