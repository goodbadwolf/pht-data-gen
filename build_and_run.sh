#!/bin/bash

build() {
    cd ospray-studio/build || return 1
    if ! make -j ospStudio; then
        return 1
    fi
    cd ../..
    return 0
}

mode="pht"
scene=""
spp="4"
dev_mode=false
renderer="pathtracer"
start_frame="0"
end_frame="-1"

run() {
    OSP_OPTIONS="${mode}"

    if [ "$dev_mode" = true ]; then
        OSP_OPTIONS+=" --resolution 256x256"
    else
        OSP_OPTIONS+=" --resolution 512x512"
    fi

    OSP_OPTIONS+=" --renderer ${renderer}"

    if [ "$mode" = "pht" ] && [ "$renderer" = "pathtracer" ]; then
        OSP_OPTIONS+=" --spp ${spp}"
    fi

    if [ "$renderer" = "pathtracer" ]; then
        spp_padded=$(printf "%06d" "$spp")
        suffix="${spp_padded}spp"
    else
        suffix="scivis"
    fi

    OSP_OPTIONS+=" --pixelfilter 0"
    OSP_OPTIONS+=" --image ${scene}_${suffix}"
    OSP_OPTIONS+=" --saveAlbedo"
    OSP_OPTIONS+=" --saveDepth"
    OSP_OPTIONS+=" --saveNormal"
    OSP_OPTIONS+=" --format png"

    if [ "$mode" = "pht" ]; then
        OSP_OPTIONS+=" --cameraGenerator fibonacci"
        OSP_OPTIONS+=" --cameraGeneratorFlipYZ"
        OSP_OPTIONS+=" --numFrames 32"
        OSP_OPTIONS+=" --forceOverwrite"
        OSP_OPTIONS+=" --outputPath images/${scene}_${suffix}"
        OSP_OPTIONS+=" --startFrame ${start_frame}"
        OSP_OPTIONS+=" --endFrame ${end_frame}"
    fi

    additional_options_file="ospStudio-scenes/${scene}_opts.txt"
    if [ -f "$additional_options_file" ]; then
        OSP_OPTIONS+=" $(cat "$additional_options_file")"
    fi

    if [ "$mode" = "pht" ]; then
        additional_options_file="ospStudio-scenes/${scene}_pht_opts.txt"
        if [ -f "$additional_options_file" ]; then
            OSP_OPTIONS+=" $(cat "$additional_options_file")"
        fi
    fi
    echo "Using options ${OSP_OPTIONS}"

    OSP_STUDIO_BASE="./ospray-studio/build/ospStudio"
    OSP_STUDIO_CMD="${OSP_STUDIO_BASE} ${OSP_OPTIONS}"

    if [ "$scene" = "none" ]; then
        echo "Running ospStudio without any file"
        ${OSP_STUDIO_CMD}
    else
        scene_file="ospStudio-scenes/${scene}.sg"
        if [ -f "$scene_file" ]; then
            echo "Running ospStudio with ${scene_file}"
            ${OSP_STUDIO_CMD} "$scene_file"
        else
            echo "Error: Scene at path ${scene_file} not found"
            return 1
        fi
    fi

    if [ "$mode" = "gui" ] && [ "$scene" != "none" ]; then
        if [ -f "studio_scene.sg" ]; then
            echo "Updating ${scene}.sg"
            mv studio_scene.sg "ospStudio-scenes/${scene}.sg"
        fi
    fi
}

usage() {
    echo "Usage: $0 -m|--mode <mode> -s|--scene <scene> [-p|--spp <spp>] [-d|--dev-mode] [-f|--start-frame <start_frame>] [-e|--end-frame <end_frame>] [-r|--renderer <renderer>]"
    echo "  -m, --mode      Mode: gui or pht (required)"
    echo "  -s, --scene     Scene name (required)"
    echo "  -p, --spp       Samples per pixel (optional, default: 1)"
    echo "  -d, --dev-mode  Enable development mode (optional flag)"
    echo "  -f, --start-frame Starting frame number (optional, default: 0)"
    echo "  -e, --end-frame Ending frame number (optional, default: -1)"
    echo "  -r, --renderer  Renderer: pathtracer or scivis (optional, default: pathtracer)"
    exit 1
}

main() {
    # Parse command line arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
        -m | --mode)
            mode="$2"
            shift 2
            ;;
        -s | --scene)
            scene="$2"
            shift 2
            ;;
        -p | --spp)
            spp="$2"
            shift 2
            ;;
        -r | --renderer)
            renderer="$2"
            shift 2
            ;;
        -f | --start-frame)
            start_frame="$2"
            shift 2
            ;;
        -e | --end-frame)
            end_frame="$2"
            shift 2
            ;;
        -d | --dev-mode)
            dev_mode=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            usage
            ;;
        esac
    done

    # mode must be one of: gui, pht
    if [ "$mode" != "gui" ] && [ "$mode" != "pht" ]; then
        echo "Error: mode must be one of : gui, pht"
        exit 1
    fi

    # renderer must be one of: pathtracer, scivis
    if [ "$renderer" != "pathtracer" ] && [ "$renderer" != "scivis" ]; then
        echo "Error: renderer must be one of: pathtracer, scivis"
        exit 1
    fi

    if build; then
        run
    else
        echo "Build failed"
        exit 1
    fi
}

main "$@"
