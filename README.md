# vat-blender-plugin

Blender pluging to create vertex animation textures.


## Input

## Output

## Terms

Frame: unità di base delle timeline. 

	In questo caso si parla di animazioni in uno spazio 3D:
	-l'animazione di un oggetto che si muove è descritta in timeline almeno da due KEYframe. 
	-Se un'animazione dura "50 frame" vuol dire che c'è un keyframe sul frame 1 e uno sul 51.
	-L'engine interpolerà tra informazioni salvate nel keyframe 1 e quelle salvate nel 51.
 

Static mesh: geometria di poligoni che può essere renderizzata dalla scheda grafica

	Qui la differenza è tra le static e non static meshes. Quelle non statiche (e che quindi possono muoversi nello spazio 3D) devono essere calcolate dalla CPU.
	Le mesh statiche vengono escluse da tutte una serie di calcoli e quindi riescono ad essere renderizzate in GPU. 

Vertex: unità base di una mesh

	Verteces, Edges & Faces sono i 3 "building blocks" degli oggetti 3D. 
	Un vertex è un punto nello spazio 3D ed è caratterizzato da 3 coordinate (x,y,z) e un ID.
	Un edge è la linea che unisce 2 vertici.
	Una face è la superficie determinata da 3 (o più) vertici. Ha come proprietà anche la "normale" (la direzione della faccia). 

Texture: un'immagine

	per texture si intende una qualsiasi immagine. 

Scale: un terzo di un transform (?)

	Per scale si può intendere parecchia roba, penso che ti interessi lo scale come "scala" dell'oggetto 3D.
	Ogni oggetto in uno spazio 3D ha almeno un "transform":
	transform = position (x,y,z); rotation (x,y,z); scale (x,y,z)

	
