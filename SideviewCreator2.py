bl_info = {
    "name": "Procedural Model Sideview Creator",
    "author": "levinqu",
    "version": (1, 0),
    "blender": (2, 80, 0),
    "location": "View3D > Sidebar > Sideview Creator",
    "description": "Prepare side views of procedural models for AIGC",
    "warning": "",
    "wiki_url": "",
    "category": "3D View",
}

import bpy
import os
import io
import tempfile
from math import radians
from mathutils import Vector

# 获取插件文件夹的路径
addon_directory = os.path.dirname(os.path.realpath(__file__))

# Calculate the bounding box of the visible mesh objects in the scene
def get_scene_bounding_box():
    min_coords = Vector((float('inf'), float('inf'), float('inf')))
    max_coords = Vector((float('-inf'), float('-inf'), float('-inf')))

    for obj in bpy.context.visible_objects:
        if obj.type == 'MESH':
            for coord in obj.bound_box:
                world_coord = obj.matrix_world @ Vector(coord)
                min_coords = Vector((min(min_coords[i], world_coord[i]) for i in range(3)))
                max_coords = Vector((max(max_coords[i], world_coord[i]) for i in range(3)))

    return min_coords, max_coords

# Check if the selected objects have uncleared materials or UVs
def has_uncleared_materials_or_uvs():
    for obj in bpy.context.selected_objects:
        if obj.type == 'MESH':
            if len(obj.data.materials) > 0:
                return True
            if len(obj.data.uv_layers) > 0:
                return True
    return False

# Get the layer collection with the specified name
def get_layer_collection(layer_coll, coll_name):
    for layer in layer_coll.children:
        if layer.name == coll_name:
            return layer
        else:
            result = get_layer_collection(layer, coll_name)
            if result is not None:
                return result
    return None

# Operator to generate orthogonal cameras
class GenerateCamerasOperator(bpy.types.Operator):
    bl_idname = "object.generate_orthogonal_cameras"
    bl_label = "Generate Cameras"
    bl_options = {'REGISTER', 'UNDO'}
    bl_description = "针对模型6个方位生成正交相机"  # Add the tooltip description

    # Check if the scene already has the Orthogonal Cameras collection and 6 cameras
    def check_existing_cameras(self):
        cam_collection = bpy.data.collections.get("Orthogonal Cameras")
        if cam_collection:
            existing_cameras = [obj for obj in cam_collection.objects if obj.type == 'CAMERA']
            if len(existing_cameras) == 6:
                return True
        return False

    def execute(self, context):
        if self.check_existing_cameras():
            self.report({"WARNING"}, "当前场景已存在，请勿重复创建。")
            return {"CANCELLED"}

        if has_uncleared_materials_or_uvs():
            self.report({"WARNING"}, "当前模型存在未清理材质或UV，请检查！")
            return {"CANCELLED"}

        min_coords, max_coords = get_scene_bounding_box()
        distances = max(max_coords) + 20
        bounding_box_size = max_coords - min_coords
        max_dimension = max(bounding_box_size)
        z_center = (max_coords.z + min_coords.z) / 2

        directions = [
            ('X', (distances, 0, z_center), (radians(-90), radians(180), radians(-90))),
            ('Y', (0, distances, z_center), (radians(-90), radians(180), 0)),
            ('Z', (0, 0, distances), (0, 0, 0)),
            ('-X', (-distances, 0, z_center), (radians(-90), radians(-180), radians(90))),
            ('-Y', (0, -distances, z_center), (radians(90), 0, 0)),
            ('-Z', (0, 0, -distances), (radians(180), 0, 0)),
        ]

        for dir, _, _ in directions:
            cam = bpy.data.objects.get(f"Camera_{dir}")
            if cam:
                bpy.data.objects.remove(cam)

        cam_collection = bpy.data.collections.get("Orthogonal Cameras")
        if not cam_collection:
            cam_collection = bpy.data.collections.new("Orthogonal Cameras")
            context.scene.collection.children.link(cam_collection)

        # Store the current active collection and set the active collection to "Orthogonal Cameras"
        current_collection = context.view_layer.active_layer_collection
        cam_layer_collection = get_layer_collection(context.view_layer.layer_collection, "Orthogonal Cameras")
        context.view_layer.active_layer_collection = cam_layer_collection

        for dir, loc, rot in directions:
            bpy.ops.object.camera_add(location=loc)
            cam = context.active_object
            cam.name = f"Camera_{dir}"
            cam.data.type = 'ORTHO'
            cam.rotation_euler = rot
            cam.data.ortho_scale = max_dimension * 1.1

        # Reset the active collection back to the original one
        context.view_layer.active_layer_collection = current_collection

        context.scene.render.resolution_x = 512
        context.scene.render.resolution_y = 512

        self.report({"INFO"}, "已成功创建正交相机。")

        return {'FINISHED'}

class ClearMaterialsUVOperator(bpy.types.Operator):
    bl_idname = "object.clear_materials_uv"
    bl_label = "Clear"
    bl_description = "清理模型当前UV，材质以及场景灯光"  # Add the tooltip description
    
    def remove_lights(self, context):
        for obj in context.scene.objects:
            if obj.type == 'LIGHT':
                bpy.data.objects.remove(obj)

    def execute(self, context):
        for obj in bpy.context.selected_objects:
            if obj.type == 'MESH':
                bpy.context.view_layer.objects.active = obj
                if bpy.context.active_object is not None:
                    for i in range(len(obj.data.materials)):
                        bpy.context.active_object.active_material_index = 0
                        bpy.ops.object.material_slot_remove()
                    while obj.data.uv_layers:
                        bpy.ops.mesh.uv_texture_remove({'object': obj})
        
        self.remove_lights(context)
        self.report({"INFO"}, "已清理模型自身UV，材质和灯光。")
        
        return {'FINISHED'}

def create_compositing_nodes(scene):
    # Enable compositing and use nodes
    scene.use_nodes = True

    # Clear existing nodes
    tree = scene.node_tree
    tree.nodes.clear()

    # Create new nodes
    input_node = tree.nodes.new(type='CompositorNodeRLayers')
    mix_node = tree.nodes.new(type='CompositorNodeMixRGB')
    output_node = tree.nodes.new(type='CompositorNodeComposite')

    # Set Mix node properties
    mix_node.use_alpha = True

    # Link nodes
    tree.links.new(input_node.outputs['Freestyle'], mix_node.inputs[2])
    tree.links.new(mix_node.outputs['Image'], output_node.inputs['Image'])

import io
import os
import tempfile

class RENDERSETTINGS_OT_render_image(bpy.types.Operator):
    bl_idname = "object.render_image_button"
    bl_label = "Render Lineart Image"
    bl_description = "渲染线框稿"

    def execute(self, context):
        try:
            from PIL import Image
        except ImportError:
            print("正在安装 Pillow 库，请稍候...")
            import sys
            import subprocess
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", "pillow"])
                from PIL import Image  # Import Image after installing
            except subprocess.CalledProcessError as e:
                self.report({"WARNING"}, "无法安装 Pillow 库。请手动安装。")
                return {'CANCELLED'}

        bpy.context.scene.render.use_freestyle = True
        bpy.context.scene.view_layers["ViewLayer"].use_freestyle = True

        freestyle_settings = bpy.context.scene.view_layers["ViewLayer"].freestyle_settings
        freestyle_settings.as_render_pass = True
        freestyle_settings.use_culling = True

        create_compositing_nodes(context.scene)

        output_folder = context.scene.sideview_creator_props.output_folder

        if not output_folder:
            self.report({"WARNING"}, "警告：请先指定渲染输出文件夹路径！")
            return {'CANCELLED'}

        if not os.path.exists(output_folder):
            os.makedirs(output_folder)

        rendered_images = {}

        # Iterate through all cameras in the "Orthogonal Cameras" collection
        cam_collection = bpy.data.collections.get("Orthogonal Cameras")
        if cam_collection:
            for obj in cam_collection.objects:
                if obj.type == 'CAMERA':
                    # Set the current camera as the active camera for rendering
                    context.scene.camera = obj

                    # Render the image
                    bpy.ops.render.render('EXEC_DEFAULT', animation=False, write_still=False, scene=context.scene.name)

                    # Save the rendered image to a temporary file
                    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temp_file:
                        temp_path = temp_file.name
                        bpy.context.scene.render.image_settings.file_format = 'PNG'
                        img = bpy.data.images['Render Result']
                        img.save_render(temp_path, scene=context.scene)  # Use "scene" as a keyword argument

                        # Read the temporary file into a memory buffer and store the rendered image in the dictionary
                        with open(temp_path, "rb") as file:
                            buffer = io.BytesIO(file.read())
                            rendered_images[obj.name] = Image.open(buffer)

                    # Delete the temporary file
                    try:
                        os.unlink(temp_path)  # Use os.unlink() instead of os.remove()
                    except PermissionError as e:
                        print(f"无法删除临时文件 {temp_path}：{e}")

        self.create_collage(output_folder, Image, rendered_images)

        print("已应用Freestyle lineart渲染设置并渲染所有正交相机视图。")

        return {'FINISHED'}

    def create_collage(self, output_folder, Image, rendered_images):
        collage_width = 512 * 3
        collage_height = 512 * 2
        collage = Image.new("RGBA", (collage_width, collage_height))

        image_order = ["Camera_X", "Camera_Y", "Camera_Z", "Camera_-X", "Camera_-Y", "Camera_-Z"]

        for i, image_name in enumerate(image_order):
            if image_name in rendered_images:
                img = rendered_images[image_name]

                x = (i % 3) * 512
                y = (i // 3) * 512

                collage.paste(img, (x, y))

        collage_path = os.path.join(output_folder, "collage.png")
        collage.save(collage_path)

class OrthogonalCamerasPanel(bpy.types.Panel):
    bl_label = "Sideviews Creator"
    bl_idname = "VIEW3D_PT_orthogonal_cameras"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Sideviews Creator"

    def draw(self, context):
        layout = self.layout
        props = context.scene.sideview_creator_props

        layout.operator("object.clear_materials_uv")
        layout.operator("object.generate_orthogonal_cameras")
        layout.operator("object.camera_projection")  # Add the "Camera UV Projection" button
        layout.label(text="MaterialFile")  # Change the label
        layout.prop(props, "blend_file_path", text="", icon='FILE_FOLDER')  # Remove the text from the input field
        layout.label(text="AssetsFolder")  # Change the label
        layout.prop(props, "output_folder", text="", icon='FILE_FOLDER')  # Remove the text from the input field
        layout.operator("object.render_image_button")  # Add the "Render Lineart Image" button
        layout.operator("object.apply_textures")  # Move the "Apply Textures" button

class SideviewCreatorProperties(bpy.types.PropertyGroup):
    output_folder: bpy.props.StringProperty(
        name="AssetsFolder",
        description="指定渲染输出线框稿路径（默认512），以及新贴图导入路径",  # Add the tooltip description
        default="",
        maxlen=1024,
        subtype='DIR_PATH',
    )
    blend_file_path: bpy.props.StringProperty(
        name="MaterialFile",
        description="请选择MaterialFile.Blend文件所在的文件夹路径",  # Add the tooltip description
        default="",
        maxlen=1024,
        subtype="FILE_PATH"  # Change this line from 'DIR_PATH' to 'FILE_PATH'
    )
    current_output_index: bpy.props.IntProperty(default=0)

class CameraProjectionOperator(bpy.types.Operator):
    bl_idname = "object.camera_projection"
    bl_label = "Camera UV Projection"

    def invoke(self, context, event):
        # Check if there are any selected objects
        if not context.selected_objects:
            self.report({"WARNING"}, "请先选择需要投射UV的模型！")
            return {'CANCELLED'}

        # Check if at least one selected object is a mesh
        if not any(obj.type == 'MESH' for obj in context.selected_objects):
            self.report({"WARNING"}, "请先选择需要投射UV的模型！")
            return {'CANCELLED'}

        # Check if the 6 orthogonal cameras have been generated
        cam_collection = bpy.data.collections.get("Orthogonal Cameras")
        if not cam_collection or len([obj for obj in cam_collection.objects if obj.type == 'CAMERA']) != 6:
            self.report({"WARNING"}, "请先创建投射相机！")
            return {'CANCELLED'}

        return self.execute(context)

    def execute(self, context):
        # Store the current active object and mode
        active_object = context.active_object
        current_mode = context.active_object.mode

        # Switch to Edit mode
        bpy.ops.object.mode_set(mode='EDIT')

        # Iterate through all cameras in the "Orthogonal Cameras" collection
        cam_collection = bpy.data.collections.get("Orthogonal Cameras")
        if cam_collection:
            for obj in cam_collection.objects:
                if obj.type == 'CAMERA':
                    # Set the current camera as the active camera for rendering
                    context.scene.camera = obj

                    # Set the 3D viewport to the current camera view
                    for area in bpy.context.screen.areas:
                        if area.type == 'VIEW_3D':
                            area.spaces[0].region_3d.view_perspective = 'CAMERA'

                    # Create a new UV map for the current camera projection
                    uv_map = active_object.data.uv_layers.new(name=f"UV_{obj.name}")

                    # Set the new UV map as the active UV map
                    active_object.data.uv_layers.active = uv_map

                    # Execute the "Project From View" operation for the current camera view
                    bpy.ops.uv.project_from_view(camera_bounds=True, correct_aspect=False, scale_to_bounds=False)
        # Restore the original mode
        bpy.ops.object.mode_set(mode=current_mode)

        self.report({"INFO"}, "已完成6个正交相机视角的UV投影。")

        return {'FINISHED'}

class NextTryOperator(bpy.types.Operator):
    bl_idname = "object.next_try"
    bl_label = "Next Try"
    bl_description = "应用AIGC贴图到当前模型"

    def execute(self, context):
        props = context.scene.sideview_creator_props
        output_folder = props.output_folder

        if not output_folder:
            self.report({"WARNING"}, "请先选择新贴图储存路径并且按照规范正确命名！")
            return {'CANCELLED'}

        # 更新当前的AIGC_OUTPUT_N值
        props.current_output_index += 1

        # 查找下一个存在的AIGC_OUTPUT_N图像
        found_next_image = False
        for i in range(props.current_output_index, 11):
            temp_path = os.path.join(output_folder, f"AIGC_OUTPUT_{i:02}.png")
            if os.path.exists(temp_path):
                props.current_output_index = i
                found_next_image = True
                break

        # 如果没有找到下一个图像，则从第一个图像开始查找
        if not found_next_image:
            for i in range(1, props.current_output_index):
                temp_path = os.path.join(output_folder, f"AIGC_OUTPUT_{i:02}.png")
                if os.path.exists(temp_path):
                    props.current_output_index = i
                    found_next_image = True
                    break

        if not found_next_image:
            self.report({"WARNING"}, "没有找到下一个AIGC_OUTPUT_N图像。")
            return {'CANCELLED'}

        # 调用ApplyTexturesOperator操作，并传递当前的AIGC_OUTPUT_N值
        bpy.ops.object.apply_textures(output_index=props.current_output_index)

        self.report({"INFO"}, f"已应用 AIGC_OUTPUT_{props.current_output_index:02} 贴图到当前模型。")

        return {'FINISHED'}

class ApplyTexturesOperator(bpy.types.Operator):
    bl_idname = "object.apply_textures"
    bl_label = "Apply Textures"
    bl_description = "应用AIGC贴图到当前模型"

    output_index: bpy.props.IntProperty(default=1)

    def execute(self, context):
        from PIL import Image

        # Check if the user specified an assets folder
        output_folder = context.scene.sideview_creator_props.output_folder
        if not output_folder:
            self.report({"WARNING"}, "请先选择新贴图储存路径并且按照规范正确命名！")
            return {'CANCELLED'}

        # Find the AIGC_OUTPUT_N image based on output_index
        if self.output_index > 0:
            temp_path = os.path.join(output_folder, f"AIGC_OUTPUT_{self.output_index:02}.png")
            if os.path.exists(temp_path):
                collage_path = temp_path
            else:
                self.report({"WARNING"}, f"当前文件夹中不存在AIGC_OUTPUT_{self.output_index:02}贴图，请检查。")
                return {'CANCELLED'}
        else:
            for i in range(1, 11):
                temp_path = os.path.join(output_folder, f"AIGC_OUTPUT_{i:02}.png")
                if os.path.exists(temp_path):
                    collage_path = temp_path
                    break

        # Check if an AIGC_OUTPUT_N image was found
        if not collage_path:
            self.report({"WARNING"}, "当前文件夹中不存在AIGC_OUTPUT贴图，请检查。")
            return {'CANCELLED'}

        collage = Image.open(collage_path)

        # Set the name of the pre-made material
        pre_made_material_name = "ApplyTextures"

        # Get the pre-made material
        pre_made_material = bpy.data.materials.get(pre_made_material_name)

        # Get the user-provided path to the MaterialFile.blend file
        blend_file_path = os.path.join(addon_directory, "MaterialFile.blend")

        if not blend_file_path:
            self.report({"WARNING"}, "请先提供 MaterialFile.blend 路径以便正确检索材质！")
            return {'CANCELLED'}

        # If the pre-made material is not found, try to append it from the MaterialFile.blend file
        if not pre_made_material:
            if os.path.exists(blend_file_path):
                with bpy.data.libraries.load(blend_file_path) as (data_from, data_to):
                    if pre_made_material_name in data_from.materials:
                        data_to.materials = [pre_made_material_name]
                pre_made_material = bpy.data.materials.get(pre_made_material_name)
            else:
                self.report({"WARNING"}, f"预制材质文件 '{blend_file_path}' 未找到。请确保路径正确。")
                return {'CANCELLED'}

        # Check if the pre-made material was successfully appended
        if not pre_made_material:
            self.report({"WARNING"}, f"预制材质 '{pre_made_material_name}' 未找到。请确保它存在于预制材质文件中。")
            return {'CANCELLED'}

        # Define the order and positions of the sub-textures in the collage
        sub_texture_order = ["T_B_X", "T_B_Y", "T_B_Z", "T_B_-X", "T_B_-Y", "T_B_-Z"]
        sub_texture_positions = [(0, 0), (512, 0), (1024, 0), (0, 512), (512, 512), (1024, 512)]

        # Crop the sub-textures from the collage and save them to the AssetsFolder
        sub_textures = {}
        for i, texture_name in enumerate(sub_texture_order):
            x, y = sub_texture_positions[i]
            sub_texture = collage.crop((x, y, x + 512, y + 512))
            sub_textures[texture_name] = sub_texture

            sub_texture_path = os.path.join(output_folder, f"{texture_name}.png")
            sub_texture.save(sub_texture_path)

        # Apply the pre-made material to the selected objects
        for obj in bpy.context.selected_objects:
            if obj.type == 'MESH':
                # Clear existing materials
                obj.data.materials.clear()

                # Assign the pre-made material
                obj.data.materials.append(pre_made_material)

                # Set the UV Map nodes in the material to use the corresponding UV maps
                uv_map_nodes = [node for node in pre_made_material.node_tree.nodes if node.type == 'UVMAP']
                uv_maps = obj.data.uv_layers

                for node in uv_map_nodes:
                    matching_uv_map = next((uv_map for uv_map in uv_maps if uv_map.name == node.label), None)
                    if matching_uv_map:
                        node.uv_map = matching_uv_map.name
                    else:
                        self.report({"WARNING"}, f"未找到与节点 '{node.name}' 的 Label '{node.label}' 对应的 UV Map。请确保 UV Map 名称正确。")

                # Set the Image Texture nodes in the material to use the corresponding images
                image_texture_nodes = [node for node in pre_made_material.node_tree.nodes if node.type == 'TEX_IMAGE']

                for node in image_texture_nodes:
                    tag = node.label
                    image_name = f"T_B_{tag.split('_')[-1]}"
                    image_path = os.path.join(output_folder, f"{image_name}.png")

                    if os.path.exists(image_path):
                        img = bpy.data.images.load(image_path)
                        node.image = img
                    else:
                        self.report({"WARNING"}, f"贴图 '{image_name}' 丢失，请检查！")

        self.report({"INFO"}, "已将预制材质应用于选定的对象。")
        self.report({"INFO"}, f"已应用 AIGC_OUTPUT_{self.output_index:02} 贴图到当前模型。")

        return {'FINISHED'}

class OrthogonalCamerasPanel(bpy.types.Panel):
    bl_label = "Sideviews Creator"
    bl_idname = "VIEW3D_PT_orthogonal_cameras"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Sideviews Creator"

    def draw(self, context):
        layout = self.layout
        props = context.scene.sideview_creator_props

        layout.operator("object.clear_materials_uv")
        layout.operator("object.generate_orthogonal_cameras")
        layout.operator("object.camera_projection")  # Add the "Camera UV Projection" button
        #layout.prop(props, "blend_file_path")  # Move the text input for the MaterialFile.blend path
        layout.prop(props, "output_folder", text="AssetsFolder")
        layout.operator("object.render_image_button")  # Add the "Render Lineart Image" button
        layout.operator("object.apply_textures")  # Move the "Apply Textures" button
        layout.operator("object.next_try")  # 新增"Next Try"按钮

def register():
   # Check if the Pillow library is installed, and try to install it if it's not
    try:
        import PIL
    except ImportError:
        import sys
        import subprocess
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "pillow"])
        except subprocess.CalledProcessError as e:
            print("无法安装 Pillow 库。请手动安装。")
            return
    bpy.utils.register_class(GenerateCamerasOperator)
    bpy.utils.register_class(ClearMaterialsUVOperator)
    bpy.utils.register_class(RENDERSETTINGS_OT_render_image)
    bpy.utils.register_class(OrthogonalCamerasPanel)
    bpy.utils.register_class(SideviewCreatorProperties)
    bpy.types.Scene.sideview_creator_props = bpy.props.PointerProperty(type=SideviewCreatorProperties)
    bpy.utils.register_class(CameraProjectionOperator)
    bpy.utils.register_class(ApplyTexturesOperator)
    bpy.utils.register_class(NextTryOperator)

def unregister():
    bpy.utils.unregister_class(GenerateCamerasOperator)
    bpy.utils.unregister_class(ClearMaterialsUVOperator)
    bpy.utils.unregister_class(RENDERSETTINGS_OT_render_image)
    bpy.utils.unregister_class(OrthogonalCamerasPanel)
    bpy.utils.unregister_class(SideviewCreatorProperties)
    del bpy.types.Scene.sideview_creator_props
    bpy.utils.unregister_class(CameraProjectionOperator)
    bpy.utils.unregister_class(ApplyTexturesOperator)
    bpy.utils.unregister_class(NextTryOperator)

if __name__ == "__main__":
    register()